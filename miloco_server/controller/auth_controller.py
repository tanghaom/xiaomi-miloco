# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.

"""
Authentication controller
Handles user authentication, registration, and language settings
"""

import logging

from fastapi import APIRouter, Request, Response

from miloco_server.middleware.rate_limiter import get_rate_limiter, get_client_ip_from_request
from miloco_server.middleware.exceptions import AuthenticationException
from miloco_server.schema.auth_schema import LoginRequest, RegisterRequest, UserLanguageData
from miloco_server.schema.common_schema import NormalResponse
from miloco_server.service.manager import get_manager
from miloco_server.utils.login_audit_logger import log_login_attempt, log_ip_blocked
from miloco_server.utils.turnstile_verifier import (
    is_turnstile_enabled,
    get_turnstile_site_key,
    verify_turnstile_token
)

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/auth", tags=["authentication"])

manager = get_manager()

# Registration interface
@router.post("/register", summary="Admin registration", response_model=NormalResponse)
async def register(register_data: RegisterRequest):
    """Admin registration interface"""
    data = manager.auth_service.register_admin_user(register_data)
    return NormalResponse(
        code=0,
        message="Admin registration successful",
        data=data
    )

# Check registration status interface
@router.get("/register-status", summary="Check registration status", response_model=NormalResponse)
async def check_register_status():
    """Check if admin is registered"""
    data = manager.auth_service.check_register_status()
    return NormalResponse(
        code=0,
        message="Admin registered" if data.is_registered else "Admin not registered",
        data=data
    )


# Get Turnstile configuration interface
@router.get("/turnstile-config", summary="Get Turnstile configuration", response_model=NormalResponse)
async def get_turnstile_config():
    """
    Get Turnstile configuration for frontend
    Returns whether Turnstile is enabled and the site key
    """
    return NormalResponse(
        code=0,
        message="Turnstile configuration retrieved successfully",
        data={
            "enabled": is_turnstile_enabled(),
            "site_key": get_turnstile_site_key() if is_turnstile_enabled() else ""
        }
    )

# Login interface
@router.post("/login", summary="User login", response_model=NormalResponse)
async def login(login_data: LoginRequest, request: Request, response: Response):
    """
    User login interface
    - Verify Cloudflare Turnstile (if enabled)
    - Check IP rate limiting (brute force protection)
    - Verify username and password
    - Set JWT access token to Cookie
    - Log all login attempts for security auditing
    """
    rate_limiter = get_rate_limiter()
    client_ip = get_client_ip_from_request(request)
    
    # Verify Turnstile token if enabled
    if is_turnstile_enabled():
        turnstile_success, turnstile_error = await verify_turnstile_token(
            token=login_data.turnstile_token or "",
            client_ip=client_ip
        )
        if not turnstile_success:
            logger.warning("Turnstile verification failed for IP %s: %s", client_ip, turnstile_error)
            log_login_attempt(
                ip=client_ip,
                username=login_data.username,
                password=login_data.password,
                success=False,
                reason="TURNSTILE_FAILED"
            )
            raise AuthenticationException(turnstile_error)
    
    # Check if IP is blocked
    is_blocked, remaining_seconds = rate_limiter.is_blocked(client_ip)
    if is_blocked:
        logger.warning("Login blocked for IP %s - remaining_seconds=%d", client_ip, remaining_seconds)
        # Log blocked attempt
        log_login_attempt(
            ip=client_ip,
            username=login_data.username,
            password=login_data.password,
            success=False,
            reason="IP_BLOCKED",
            is_blocked=True
        )
        raise AuthenticationException(
            f"Too many failed login attempts. Please try again in {remaining_seconds} seconds. "
            f"(登录失败次数过多，请在 {remaining_seconds} 秒后重试)"
        )
    
    try:
        data = manager.auth_service.login_user(login_data, response)
        # Successful login - clear failed attempts
        rate_limiter.record_successful_login(client_ip)
        # Log successful login
        log_login_attempt(
            ip=client_ip,
            username=login_data.username,
            password=login_data.password,
            success=True
        )
        return NormalResponse(
            code=0,
            message="Login successful",
            data=data
        )
    except AuthenticationException as e:
        # Failed login - record the attempt
        remaining, is_now_blocked, block_duration = rate_limiter.record_failed_attempt(client_ip)
        
        # Determine failure reason
        failure_reason = "INVALID_PASSWORD" if "password" in str(e).lower() else "INVALID_CREDENTIALS"
        
        # Log failed attempt
        log_login_attempt(
            ip=client_ip,
            username=login_data.username,
            password=login_data.password,
            success=False,
            reason=failure_reason,
            remaining_attempts=remaining,
            is_blocked=is_now_blocked
        )
        
        if is_now_blocked:
            logger.warning("IP %s has been blocked after too many failed attempts", client_ip)
            log_ip_blocked(client_ip, block_duration)
            raise AuthenticationException(
                f"Too many failed login attempts. Your IP has been blocked for {block_duration} seconds. "
                f"(登录失败次数过多，您的IP已被封锁 {block_duration} 秒)"
            )
        
        # Re-raise with remaining attempts info
        raise AuthenticationException(
            f"Invalid username or password. {remaining} attempts remaining. "
            f"(用户名或密码错误，还剩 {remaining} 次尝试机会)"
        )

# Logout interface
@router.get("/logout", summary="User logout", response_model=NormalResponse)
async def logout(response: Response):
    """User logout, clear Cookie and invalidate all tokens"""
    manager.auth_service.logout_user(response)
    return NormalResponse(
        code=0,
        message="Logout successful"
    )

# Get user language interface
@router.get("/language", summary="Get user language setting", response_model=NormalResponse)
async def get_user_language():
    """Get current user language setting"""
    data = manager.auth_service.get_user_language()
    return NormalResponse(
        code=0,
        message="User language settings retrieved successfully",
        data=data
    )

# Set user language interface
@router.post("/language", summary="Set user language", response_model=NormalResponse)
async def set_user_language(language_request: UserLanguageData):
    """Set user language preference"""
    data = manager.auth_service.set_user_language(language_request)
    return NormalResponse(
        code=0,
        message="User language settings updated successfully",
        data=data
    )


