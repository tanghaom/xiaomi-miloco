# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.

"""
Xiaomi IoT controller
Handles Xiaomi IoT device login, authorization, and device management
"""
import asyncio
import logging
import os
import re
from collections import OrderedDict
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, Depends, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.websockets import WebSocketDisconnect, WebSocketState
from pydantic import BaseModel, Field

from miloco_server.middleware import (
    verify_token,
    verify_websocket_token
)
from miloco_server.middleware import MiotServiceException, ResourceNotFoundException
from miloco_server.schema.common_schema import NormalResponse
from miloco_server.service.manager import get_manager
from miloco_server.config import STORAGE_DIR

logger = logging.getLogger(name=__name__)

router = APIRouter(prefix="/miot", tags=["Xiaomi IoT"])

manager = get_manager()
RAW_DUMP_ROOT = STORAGE_DIR / "debug" / "raw_stream"


def _sanitize_name(value: str) -> str:
    """Make camera id safe for filesystem usage."""
    return re.sub(r"[^0-9A-Za-z._-]", "_", value)


class RawVideoDumpSession:
    """Represent a single raw video dump session."""

    def __init__(self, camera_id: str, channel: int, base_dir: Path, max_bytes: int):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_id = _sanitize_name(camera_id)
        self.file_path = base_dir / f"{safe_id}_ch{channel}_{timestamp}.h26x"
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.file_path.open("wb")
        self.max_bytes = max_bytes
        self.bytes_written = 0
        self.finished = False
        self.close_reason = "timeout"
        self._event = asyncio.Event()

    def write(self, payload: bytes) -> None:
        if self.finished:
            return
        self._file.write(payload)
        self.bytes_written += len(payload)
        if self.bytes_written >= self.max_bytes:
            self.finish(reason="max_bytes")

    async def wait_finished(self) -> None:
        await self._event.wait()

    async def auto_close_after(self, seconds: int) -> None:
        try:
            await asyncio.sleep(seconds)
        finally:
            if not self.finished:
                self.finish("timeout")

    def finish(self, reason: str = "timeout") -> None:
        if self.finished:
            return
        self.close_reason = reason
        self.finished = True
        if not self._file.closed:
            self._file.flush()
            self._file.close()
        self._event.set()


class RawVideoDumpManager:
    """Manage raw video dump sessions for troubleshooting."""

    def __init__(self, base_dir: Path):
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def capture_once(
        self,
        miot_service,
        camera_id: str,
        channel: int,
        duration_seconds: int = 5,
        max_bytes: int = 4 * 1024 * 1024,
    ) -> tuple[Path, int, str, int]:
        safe_duration = max(1, min(duration_seconds, 30))
        byte_limit = max(1024, min(max_bytes, 20 * 1024 * 1024))
        async with self._lock:
            session = RawVideoDumpSession(camera_id, channel, self._base_dir, byte_limit)
            timeout_task = asyncio.create_task(session.auto_close_after(safe_duration))

            async def _raw_callback(did: str, data: bytes, ts: int, seq: int, ch: int) -> None:
                if session.finished:
                    return
                session.write(data)

            stream_started = False
            try:
                await miot_service.start_video_stream(camera_id, channel, _raw_callback)
                stream_started = True
                await session.wait_finished()
            finally:
                timeout_task.cancel()
                with suppress(asyncio.CancelledError):
                    await timeout_task
                if stream_started:
                    await miot_service.stop_video_stream(camera_id, channel)
                if not session.finished:
                    session.finish("stopped")
            return session.file_path, session.bytes_written, session.close_reason, safe_duration


raw_video_dump_manager = RawVideoDumpManager(RAW_DUMP_ROOT)


class RawDumpRequest(BaseModel):
    """Request body for raw stream dump."""

    camera_id: str = Field(description="Camera device ID (did)")
    channel: int = Field(default=0, ge=0, description="Camera channel")
    duration_seconds: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Capture duration in seconds (1-30)",
    )
    max_bytes: int = Field(
        default=4 * 1024 * 1024,
        ge=1024,
        le=20 * 1024 * 1024,
        description="Maximum bytes to write (1KB-20MB)",
    )


@router.get("/xiaomi_home_callback", summary="Xiaomi Home authorization callback", response_class=HTMLResponse)
async def xiaomi_home_callback(code: str, state: str):
    """Xiaomi Home authorization callback handler"""
    logger.info(
        "Xiaomi Home authorization callback: code=%s, state=%s", code, state)

    # Read HTML template file
    template_path = os.path.join(os.path.dirname(
        __file__), "..", "templates", "miot_login_callback.html")
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            template_content = f.read()
    except FileNotFoundError as exc:
        logger.error("HTML template file not found: %s", template_path)
        raise ResourceNotFoundException("HTML template file not found") from exc

    try:
        await manager.miot_service.process_xiaomi_home_callback(code, state)

        logger.info("Xiaomi Home authorization callback processed successfully")

        # Authorization successful
        title = "Authorization Successful"
        content = "Xiaomi Home authorization successful, you can close this page"
        button = "Close"
        success = True

    except MiotServiceException as e:
        logger.error(
            "Xiaomi Home authorization callback processing failed - MiOT service error: %s", e.message)

        # Authorization failed
        title = "Authorization Failed"
        content = f"Xiaomi Home authorization failed: {e.message}"
        button = "Close"
        success = False

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(
            "Unknown error occurred during Xiaomi Home authorization callback processing: %s", str(e))

        # Unknown error
        title = "Authorization Failed"
        content = f"Unknown error occurred during Xiaomi Home authorization: {str(e)}"
        button = "Close"
        success = False

    # Fill HTML template
    web_page = template_content.replace("TITLE_PLACEHOLDER", title)
    web_page = web_page.replace("CONTENT_PLACEHOLDER", content)
    web_page = web_page.replace("BUTTON_PLACEHOLDER", button)
    web_page = web_page.replace(
        "STATUS_PLACEHOLDER", "true" if success else "false")

    return HTMLResponse(content=web_page)


@router.get("/login_status", summary="Check MiOT login status", response_model=NormalResponse)
async def get_miot_login_status(current_user: str = Depends(verify_token)):
    """Check MiOT login status"""
    logger.info("MiOT login status API called, user: %s", current_user)

    result = await manager.miot_service.get_miot_login_status()

    logger.info("MiOT login status: Login successful")
    return NormalResponse(
        code=0,
        message="Login status checked successfully",
        data=result
    )


@router.get(path="/user_info", summary="Get MiOT user information", response_model=NormalResponse)
async def get_miot_user_info(current_user: str = Depends(verify_token)):
    """Get MiOT user information"""
    logger.info("Get MiOT user info API called, user: %s", current_user)

    user_info = await manager.miot_service.get_miot_user_info()

    logger.info("Successfully retrieved Xiaomi Home user information")
    return NormalResponse(
        code=0,
        message="MiOT user information retrieved successfully",
        data=user_info
    )


@router.get(path="/camera_list", summary="Get MiOT camera list", response_model=NormalResponse)
async def get_miot_camera_list(current_user: str = Depends(verify_token)):
    """Get MiOT camera list"""
    logger.info("Get MiOT camera list API called, user: %s", current_user)

    camera_list = await manager.miot_service.get_miot_camera_list()

    logger.info(
        "Successfully retrieved Xiaomi Home camera list - Count: %s", len(camera_list))
    return NormalResponse(
        code=0,
        message="MiOT camera list retrieved successfully",
        data=camera_list
    )

@router.get(path="/device_list", summary="Get MiOT device list", response_model=NormalResponse)
async def get_miot_device_list(current_user: str = Depends(verify_token)):
    """Get MiOT device list"""
    logger.info("get miot device list, user: %s", current_user)
    device_list = await manager.miot_service.get_miot_device_list()
    logger.info("Successfully retrieved Xiaomi Home device list - Count: %s", len(device_list))
    return NormalResponse(
        code=0,
        message="MiOT device list retrieved successfully",
        data=device_list
    )

@router.get(path="/refresh_miot_all_info", summary="Refresh MiOT all information", response_model=NormalResponse)
async def refresh_miot_all_info(current_user: str = Depends(verify_token)):
    """Refresh MiOT all information"""
    logger.info("Refresh MiOT all info API called, user: %s", current_user)
    result = await manager.miot_service.refresh_miot_all_info()
    logger.info("MiOT information refresh completed: %s", result)
    return NormalResponse(
        code=0,
        message="MiOT information refresh completed",
        data=result
    )


@router.get(path="/refresh_miot_cameras", summary="Refresh MiOT camera information", response_model=NormalResponse)
async def refresh_miot_cameras(current_user: str = Depends(verify_token)):
    """Refresh MiOT camera information"""
    logger.info("Refresh MiOT cameras API called, user: %s", current_user)

    result = await manager.miot_service.refresh_miot_cameras()

    logger.info("Successfully refreshed Xiaomi Home camera information")
    return NormalResponse(
        code=0,
        message="MiOT camera information refreshed successfully",
        data=result
    )


@router.get(path="/refresh_miot_scenes", summary="Refresh MiOT scene information", response_model=NormalResponse)
async def refresh_miot_scenes(current_user: str = Depends(verify_token)):
    """Refresh MiOT scene information"""
    logger.info("Refresh MiOT scenes API called, user: %s", current_user)

    result = await manager.miot_service.refresh_miot_scenes()

    logger.info("Successfully refreshed Xiaomi Home scene information")
    return NormalResponse(
        code=0,
        message="MiOT scene information refreshed successfully",
        data=result
    )


@router.get(path="/refresh_miot_user_info", summary="Refresh MiOT user information", response_model=NormalResponse)
async def refresh_miot_user_info(current_user: str = Depends(verify_token)):
    """Refresh MiOT user information"""
    logger.info("Refresh MiOT user info API called, user: %s", current_user)

    result = await manager.miot_service.refresh_miot_user_info()

    logger.info("Successfully refreshed Xiaomi Home user information")
    return NormalResponse(
        code=0,
        message="MiOT user information refreshed successfully",
        data=result
    )


@router.post(
    path="/debug/raw_dump",
    summary="Dump raw camera stream for debugging",
    response_model=NormalResponse,
)
async def dump_raw_camera_stream(
    req: RawDumpRequest,
    current_user: str = Depends(verify_token),
):
    """Dump raw H264/H265 data to a file for troubleshooting."""
    file_path, byte_count, reason, used_duration = await raw_video_dump_manager.capture_once(
        manager.miot_service,
        camera_id=req.camera_id,
        channel=req.channel,
        duration_seconds=req.duration_seconds,
        max_bytes=req.max_bytes,
    )
    return NormalResponse(
        code=0,
        message="Raw video stream dumped successfully",
        data={
            "file_path": str(file_path),
            "bytes": byte_count,
            "stop_reason": reason,
            "duration_seconds": used_duration,
        },
    )


@router.get(path="/refresh_miot_devices", summary="Refresh MiOT device information", response_model=NormalResponse)
async def refresh_miot_devices(current_user: str = Depends(verify_token)):
    """Refresh MiOT device information"""
    logger.info("Refresh MiOT devices API called, user: %s", current_user)

    result = await manager.miot_service.refresh_miot_devices()

    logger.info("Successfully refreshed Xiaomi Home device information")
    return NormalResponse(
        code=0,
        message="MiOT device information refreshed successfully",
        data=result
    )


@router.get(path="/miot_scene_actions", summary="Get MiOT scene actions list", response_model=NormalResponse)
async def get_miot_scene_actions(current_user: str = Depends(verify_token)):
    """Get MiOT scene actions list"""
    logger.info("Get MiOT actions API called, user: %s", current_user)
    actions = await manager.miot_service.get_miot_scene_actions()
    return NormalResponse(
        code=0,
        message="MiOT scene actions list retrieved successfully",
        data=actions
    )

@router.get(path="/send_notify", summary="Send notification", response_model=NormalResponse)
async def send_notify(notify: str, current_user: str = Depends(verify_token)):
    """Send notification"""
    logger.info("Send notify API called, notify: %s, user: %s", notify, current_user)
    await manager.miot_service.send_notify(notify)
    return NormalResponse(
        code=0,
        message="Notification sent successfully",
        data=None
    )


class MIoTVideoStreamManager:
    """MIoT Video WS Manager."""
    _CAMERA_CONNECT_COUNT_MAX: int = 4
    # key=camera_id.channel, value={user_name: {user_tag: Dict[id, websocket]}}
    _camera_connect_map: Dict[str, Dict[str, OrderedDict[str, WebSocket]]]
    _camera_connect_id: int

    def __init__(self):
        self._camera_connect_map = {}
        self._camera_connect_id = 0
        logger.info("Init MIoT Video WS Manager")

    async def new_connection(
        self, websocket: WebSocket, user_name: str, token_hash: str,  camera_id: str, channel: int
    ) -> str:
        """New video stream connection."""
        camera_tag = f"{camera_id}.{channel}"
        if camera_tag not in self._camera_connect_map or not self._camera_connect_map[camera_tag]:
            self._camera_connect_map[camera_tag] = {}
            await manager.miot_service.start_video_stream(
                camera_id=camera_id, channel=channel, callback=self.__video_stream_callback)
            logger.info("Start video stream, %s.%d", camera_id, channel)
        user_tag = f"{user_name}.{token_hash}"
        self._camera_connect_map[camera_tag].setdefault(user_tag, OrderedDict())
        connection_id = str(self._camera_connect_id)
        self._camera_connect_id += 1
        self._camera_connect_map[camera_tag][user_tag][connection_id] = websocket
        logger.info("New video stream connection, %s, %s, %s", camera_tag, user_tag, connection_id)
        if len(self._camera_connect_map[camera_tag][user_tag]) > self._CAMERA_CONNECT_COUNT_MAX:
            # pylint: disable=unused-variable
            logger.warning("Too many connections, %s.%d, %s, remove first connect",camera_id, channel, user_tag)
            _, ws = self._camera_connect_map[camera_tag][user_tag].popitem(last=False)
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.close()
            except Exception as err:  # pylint: disable=broad-exception-caught
                logger.error("WebSocket close error: %s", err)
        return connection_id

    async def close_connection(
        self, user_name: str, token_hash: str, camera_id: str, channel: int, cid: str
    ):
        """Close video stream connection."""
        camera_tag = f"{camera_id}.{channel}"
        user_tag = f"{user_name}.{token_hash}"
        if (
            camera_tag not in self._camera_connect_map
            or user_tag not in self._camera_connect_map[camera_tag]
            or cid not in self._camera_connect_map[camera_tag][user_tag]
        ):
            return
        logger.info("Close video stream connection, %s, %s, %s", camera_tag, user_tag, cid)

        try:
            ws = self._camera_connect_map[camera_tag][user_tag].pop(cid)
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.close()
        except Exception as err:  # pylint: disable=broad-exception-caught
            logger.error("WebSocket close error: %s", err)
        if len(self._camera_connect_map[camera_tag][user_tag]) == 0:
            self._camera_connect_map[camera_tag].pop(user_tag, None)
        if len(self._camera_connect_map[camera_tag]) == 0:
            await manager.miot_service.stop_video_stream(camera_id, channel)
            self._camera_connect_map.pop(camera_tag)
            logger.info("No connection, stop video stream, %s.%d", camera_id, channel)

    async def __video_stream_callback(
        self, did: str, data: bytes, ts: int, seq: int, channel: int
    ) -> None:
        """Video stream callback."""
        # pylint: disable=unused-argument
        camera_tag = f"{did}.{channel}"
        if camera_tag not in self._camera_connect_map:
            logger.error("No connection, %s.%d", did, channel)
            # Stop camera stream
            await manager.miot_service.stop_video_stream(did, channel)
            return
        for conn in self._camera_connect_map[camera_tag].values():
            for ws in conn.values():
                try:
                    await ws.send_bytes(data)
                except Exception as err:  # pylint: disable=broad-exception-caught
                    logger.error("WebSocket send error: %s", err)


miot_video_stream_manager = MIoTVideoStreamManager()


@router.websocket("/ws/video_stream")
async def video_stream_websocket(
    websocket: WebSocket,
    camera_id: str,
    channel: int,
    current_user: str = Depends(verify_websocket_token)
):
    """Video stream WebSocket."""
    logger.info(
        "WebSocket connection request, %s, %s.%d", current_user, camera_id, channel)
    start_time: datetime = datetime.now()
    token_hash: str = str(hash(websocket.cookies.get("access_token")))
    cid: Optional[str] = None
    try:
        await websocket.accept()
        cid = await miot_video_stream_manager.new_connection(
            websocket=websocket,
            user_name=current_user,
            token_hash=token_hash,
            camera_id=camera_id,
            channel=channel)
        while True:
            try:
                message = await websocket.receive_text()
                logger.info("Received message from client, %s", message)
            except Exception as err:  # pylint: disable=broad-exception-caught
                logger.error("WebSocket error: %s", err)
                break
    except WebSocketDisconnect:
        logger.warning("Client disconnected, %s.%d", camera_id, channel)
    except Exception as err:  # pylint: disable=broad-exception-caught
        logger.error("WebSocket error, %s", err)
        await websocket.close(code=1011, reason=f"Server error: {str(err)}")
    finally:
        logger.info(
            "Websocket connect duration[%.2fs], %s.%d",
            (datetime.now() - start_time).total_seconds(), camera_id, channel)
        if cid:
            await miot_video_stream_manager.close_connection(
                user_name=current_user, token_hash=token_hash,camera_id=camera_id, channel=channel, cid=cid)
