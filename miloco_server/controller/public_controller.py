# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.

"""
Public controller
Handles public accessible resources (no authentication required)
"""

import hashlib
import hmac
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from miloco_server.config.normal_config import IMAGE_DIR, JWT_CONFIG

logger = logging.getLogger(__name__)

router = APIRouter()

# Use JWT secret key as signing key
SIGN_SECRET = JWT_CONFIG["secret_key"]


def generate_image_sign(image_path: str) -> str:
    """
    Generate signature for image path

    Args:
        image_path: Image relative path

    Returns:
        str: Signature string
    """
    message = image_path.encode('utf-8')
    signature = hmac.new(SIGN_SECRET.encode('utf-8'), message, hashlib.sha256).hexdigest()[:16]
    return signature


def verify_image_sign(image_path: str, sign: str) -> bool:
    """
    Verify image signature

    Args:
        image_path: Image relative path
        sign: Signature to verify

    Returns:
        bool: True if signature is valid
    """
    expected_sign = generate_image_sign(image_path)
    return hmac.compare_digest(expected_sign, sign)


@router.get("/images/{image_path:path}")
async def get_public_image(
    image_path: str,
    sign: Optional[str] = Query(None, description="Image signature for verification")
):
    """
    Public image access endpoint with signature verification

    Args:
        image_path: Image relative path (e.g., '241125/hash_timestamp_id.jpg')
        sign: Signature for verification

    Returns:
        FileResponse: Image file
    """
    # Verify signature
    if not sign:
        logger.warning("Missing signature for image: %s", image_path)
        raise HTTPException(status_code=403, detail="Missing signature")

    if not verify_image_sign(image_path, sign):
        logger.warning("Invalid signature for image: %s", image_path)
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Build full file path
    full_path = os.path.join(str(IMAGE_DIR), image_path)

    # Security check: prevent directory traversal
    real_path = os.path.realpath(full_path)
    image_dir_real = os.path.realpath(str(IMAGE_DIR))
    if not real_path.startswith(image_dir_real):
        logger.warning("Directory traversal attempt: %s", image_path)
        raise HTTPException(status_code=403, detail="Access denied")

    # Check if file exists
    if not os.path.isfile(full_path):
        logger.warning("Image not found: %s", image_path)
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(full_path, media_type="image/jpeg")


def get_public_image_url(image_path: str, public_url: Optional[str] = None) -> Optional[str]:
    """
    Generate public accessible URL for an image

    Args:
        image_path: Image relative path (from media.py, e.g., '/static/camera/images/241125/xxx.jpg')
        public_url: Public base URL (e.g., 'https://your-domain.com:18000')

    Returns:
        str: Full public URL with signature, or None if public_url not configured
    """
    if not public_url:
        return None

    # Remove prefix if present
    clean_path = image_path
    prefix = '/static/camera/images/'
    if clean_path.startswith(prefix):
        clean_path = clean_path[len(prefix):]

    # Generate signature
    sign = generate_image_sign(clean_path)

    # Build full URL
    full_url = f"{public_url.rstrip('/')}/public/images/{clean_path}?sign={sign}"
    return full_url

