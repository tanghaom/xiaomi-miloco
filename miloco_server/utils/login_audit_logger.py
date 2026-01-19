# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.

"""
Login audit logger
Records all login attempts with detailed information for security auditing
"""

import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional

from miloco_server.config import LOG_DIR

# Create a dedicated logger for login auditing
_login_audit_logger: Optional[logging.Logger] = None


def _get_login_audit_logger() -> logging.Logger:
    """
    Get or create the login audit logger
    Creates a separate log file specifically for login attempts
    """
    global _login_audit_logger
    
    if _login_audit_logger is not None:
        return _login_audit_logger
    
    # Create logger
    _login_audit_logger = logging.getLogger("login_audit")
    _login_audit_logger.setLevel(logging.INFO)
    _login_audit_logger.propagate = False  # Don't propagate to root logger
    
    # Create log directory if not exists
    os.makedirs(LOG_DIR, exist_ok=True)
    
    # Create log file path
    log_file = os.path.join(LOG_DIR, "login_audit.log")
    
    # Use RotatingFileHandler to manage log file size
    # Max 10MB per file, keep 5 backup files
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8"
    )
    
    # Create formatter with detailed timestamp
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    
    # Add handler to logger
    _login_audit_logger.addHandler(file_handler)
    
    return _login_audit_logger


def log_login_attempt(
    ip: str,
    username: str,
    password: str,
    success: bool,
    reason: Optional[str] = None,
    remaining_attempts: Optional[int] = None,
    is_blocked: bool = False
) -> None:
    """
    Log a login attempt
    
    Args:
        ip: Client IP address
        username: Attempted username
        password: Attempted password (will be logged for security audit)
        success: Whether the login was successful
        reason: Reason for failure (if failed)
        remaining_attempts: Number of remaining attempts before block
        is_blocked: Whether the IP is now blocked
    """
    logger = _get_login_audit_logger()
    
    # Build log message
    status = "SUCCESS" if success else "FAILED"
    
    message_parts = [
        f"IP={ip}",
        f"username={username}",
        f"password={password}",
        f"status={status}"
    ]
    
    if reason:
        message_parts.append(f"reason={reason}")
    
    if remaining_attempts is not None:
        message_parts.append(f"remaining_attempts={remaining_attempts}")
    
    if is_blocked:
        message_parts.append("BLOCKED=YES")
    
    message = " | ".join(message_parts)
    
    if success:
        logger.info(message)
    elif is_blocked:
        logger.warning(message)
    else:
        logger.warning(message)


def log_ip_blocked(ip: str, block_duration_seconds: int) -> None:
    """
    Log when an IP gets blocked
    
    Args:
        ip: Client IP address
        block_duration_seconds: Duration of the block in seconds
    """
    logger = _get_login_audit_logger()
    logger.warning(
        "IP_BLOCKED | IP=%s | duration_seconds=%d | blocked_until=%s",
        ip,
        block_duration_seconds,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )


def log_ip_unblocked(ip: str, reason: str = "expired") -> None:
    """
    Log when an IP gets unblocked
    
    Args:
        ip: Client IP address
        reason: Reason for unblocking (expired, manual, successful_login)
    """
    logger = _get_login_audit_logger()
    logger.info("IP_UNBLOCKED | IP=%s | reason=%s", ip, reason)

