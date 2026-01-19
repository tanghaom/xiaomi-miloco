# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.

"""
Cloudflare Turnstile verification utility
Provides human verification for login protection
"""

import logging
from typing import Optional, Tuple

import httpx

from miloco_server.config import TURNSTILE_CONFIG

logger = logging.getLogger(__name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def is_turnstile_enabled() -> bool:
    """Check if Turnstile is enabled"""
    return TURNSTILE_CONFIG.get("enabled", False) and bool(TURNSTILE_CONFIG.get("secret_key"))


def get_turnstile_site_key() -> str:
    """Get the Turnstile site key for frontend use"""
    return TURNSTILE_CONFIG.get("site_key", "")


async def verify_turnstile_token(token: str, client_ip: Optional[str] = None) -> Tuple[bool, str]:
    """
    Verify Turnstile token with Cloudflare API
    
    Args:
        token: The Turnstile response token from frontend
        client_ip: Optional client IP address for additional verification
        
    Returns:
        Tuple[bool, str]: (success, error_message)
    """
    if not is_turnstile_enabled():
        logger.debug("Turnstile is disabled, skipping verification")
        return True, ""
    
    if not token:
        logger.warning("Turnstile token is empty")
        return False, "Turnstile verification required (需要完成人机验证)"
    
    secret_key = TURNSTILE_CONFIG.get("secret_key", "")
    if not secret_key:
        logger.error("Turnstile secret key is not configured")
        return False, "Turnstile configuration error"
    
    # Prepare verification request
    data = {
        "secret": secret_key,
        "response": token,
    }
    
    if client_ip:
        data["remoteip"] = client_ip
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(TURNSTILE_VERIFY_URL, data=data)
            result = response.json()
            
            success = result.get("success", False)
            
            if success:
                logger.info("Turnstile verification successful")
                return True, ""
            else:
                error_codes = result.get("error-codes", [])
                error_message = _get_error_message(error_codes)
                logger.warning(
                    "Turnstile verification failed - error_codes=%s",
                    error_codes
                )
                return False, error_message
                
    except httpx.TimeoutException:
        logger.error("Turnstile verification timeout")
        return False, "Verification timeout, please try again (验证超时，请重试)"
    except Exception as e:
        logger.error("Turnstile verification error: %s", str(e))
        return False, "Verification error, please try again (验证错误，请重试)"


def _get_error_message(error_codes: list) -> str:
    """
    Convert Turnstile error codes to human-readable messages
    
    Args:
        error_codes: List of error codes from Turnstile API
        
    Returns:
        str: Human-readable error message
    """
    error_messages = {
        "missing-input-secret": "Server configuration error",
        "invalid-input-secret": "Server configuration error",
        "missing-input-response": "Please complete the verification (请完成人机验证)",
        "invalid-input-response": "Verification failed, please try again (验证失败，请重试)",
        "bad-request": "Bad request",
        "timeout-or-duplicate": "Verification expired, please try again (验证已过期，请重试)",
        "internal-error": "Verification service error, please try again (验证服务错误，请重试)",
    }
    
    for code in error_codes:
        if code in error_messages:
            return error_messages[code]
    
    return "Verification failed, please try again (验证失败，请重试)"

