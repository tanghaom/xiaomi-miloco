# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.

"""
IP-based login rate limiter
Protects against brute force attacks by limiting failed login attempts per IP
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class IPRecord:
    """Record of login attempts for an IP"""
    failed_attempts: int = 0
    first_failed_time: float = 0.0
    blocked_until: float = 0.0


class LoginRateLimiter:
    """
    IP-based login rate limiter
    
    Features:
    - Tracks failed login attempts per IP
    - Blocks IPs after exceeding max failed attempts
    - Auto-unblocks after block duration expires
    - Resets failed count after successful login
    """
    
    def __init__(
        self,
        max_failed_attempts: int = 5,
        block_duration_seconds: int = 900,  # 15 minutes
        attempt_window_seconds: int = 600,  # 10 minutes
    ):
        """
        Initialize the rate limiter
        
        Args:
            max_failed_attempts: Maximum failed attempts before blocking (default: 5)
            block_duration_seconds: How long to block an IP in seconds (default: 15 minutes)
            attempt_window_seconds: Time window for counting failed attempts (default: 10 minutes)
        """
        self._max_failed_attempts = max_failed_attempts
        self._block_duration = block_duration_seconds
        self._attempt_window = attempt_window_seconds
        self._ip_records: dict[str, IPRecord] = defaultdict(IPRecord)
        self._lock = Lock()
        
        logger.info(
            "LoginRateLimiter initialized - max_failed_attempts=%d, "
            "block_duration=%ds, attempt_window=%ds",
            max_failed_attempts, block_duration_seconds, attempt_window_seconds
        )
    
    def _get_client_ip(self, ip: str) -> str:
        """
        Normalize client IP address
        Handle X-Forwarded-For header for reverse proxy scenarios
        """
        # If IP contains comma (X-Forwarded-For with multiple proxies), take the first one
        if ',' in ip:
            ip = ip.split(',')[0].strip()
        return ip
    
    def is_blocked(self, ip: str) -> tuple[bool, Optional[int]]:
        """
        Check if an IP is currently blocked
        
        Args:
            ip: Client IP address
            
        Returns:
            tuple[bool, Optional[int]]: (is_blocked, remaining_seconds if blocked)
        """
        ip = self._get_client_ip(ip)
        current_time = time.time()
        
        with self._lock:
            record = self._ip_records.get(ip)
            
            if record is None:
                return False, None
            
            if record.blocked_until > current_time:
                remaining = int(record.blocked_until - current_time)
                logger.warning(
                    "IP %s is blocked - remaining_seconds=%d",
                    ip, remaining
                )
                return True, remaining
            
            # Check if we should reset the record (block expired or window expired)
            if record.blocked_until > 0 and record.blocked_until <= current_time:
                # Block expired, reset the record
                self._ip_records[ip] = IPRecord()
                logger.info("IP %s block expired, record reset", ip)
                return False, None
            
            # Check if attempt window expired
            if (record.first_failed_time > 0 and 
                current_time - record.first_failed_time > self._attempt_window):
                # Window expired, reset failed attempts
                self._ip_records[ip] = IPRecord()
                logger.info("IP %s attempt window expired, record reset", ip)
                
        return False, None
    
    def record_failed_attempt(self, ip: str) -> tuple[int, bool, Optional[int]]:
        """
        Record a failed login attempt
        
        Args:
            ip: Client IP address
            
        Returns:
            tuple[int, bool, Optional[int]]: 
                (remaining_attempts, is_now_blocked, block_duration_if_blocked)
        """
        ip = self._get_client_ip(ip)
        current_time = time.time()
        
        with self._lock:
            record = self._ip_records[ip]
            
            # If this is the first failed attempt or window expired, start fresh
            if (record.first_failed_time == 0 or 
                current_time - record.first_failed_time > self._attempt_window):
                record.failed_attempts = 1
                record.first_failed_time = current_time
                record.blocked_until = 0
            else:
                record.failed_attempts += 1
            
            remaining = self._max_failed_attempts - record.failed_attempts
            
            logger.warning(
                "Failed login attempt from IP %s - attempt=%d/%d",
                ip, record.failed_attempts, self._max_failed_attempts
            )
            
            # Check if we need to block
            if record.failed_attempts >= self._max_failed_attempts:
                record.blocked_until = current_time + self._block_duration
                logger.warning(
                    "IP %s blocked for %d seconds due to too many failed attempts",
                    ip, self._block_duration
                )
                return 0, True, self._block_duration
            
            return max(0, remaining), False, None
    
    def record_successful_login(self, ip: str) -> None:
        """
        Record a successful login, reset failed attempts for the IP
        
        Args:
            ip: Client IP address
        """
        ip = self._get_client_ip(ip)
        
        with self._lock:
            if ip in self._ip_records:
                del self._ip_records[ip]
                logger.info("IP %s successful login, record cleared", ip)
    
    def get_status(self, ip: str) -> dict:
        """
        Get the current status for an IP
        
        Args:
            ip: Client IP address
            
        Returns:
            dict: Status information
        """
        ip = self._get_client_ip(ip)
        current_time = time.time()
        
        with self._lock:
            record = self._ip_records.get(ip)
            
            if record is None:
                return {
                    "ip": ip,
                    "failed_attempts": 0,
                    "remaining_attempts": self._max_failed_attempts,
                    "is_blocked": False,
                    "blocked_remaining_seconds": None
                }
            
            is_blocked = record.blocked_until > current_time
            blocked_remaining = (
                int(record.blocked_until - current_time) 
                if is_blocked else None
            )
            
            return {
                "ip": ip,
                "failed_attempts": record.failed_attempts,
                "remaining_attempts": max(0, self._max_failed_attempts - record.failed_attempts),
                "is_blocked": is_blocked,
                "blocked_remaining_seconds": blocked_remaining
            }
    
    def unblock_ip(self, ip: str) -> bool:
        """
        Manually unblock an IP (admin operation)
        
        Args:
            ip: Client IP address
            
        Returns:
            bool: True if IP was unblocked, False if IP wasn't blocked
        """
        ip = self._get_client_ip(ip)
        
        with self._lock:
            if ip in self._ip_records:
                del self._ip_records[ip]
                logger.info("IP %s manually unblocked", ip)
                return True
        return False
    
    def get_blocked_ips(self) -> list[dict]:
        """
        Get list of currently blocked IPs (admin operation)
        
        Returns:
            list[dict]: List of blocked IP information
        """
        current_time = time.time()
        blocked = []
        
        with self._lock:
            for ip, record in self._ip_records.items():
                if record.blocked_until > current_time:
                    blocked.append({
                        "ip": ip,
                        "blocked_until": record.blocked_until,
                        "remaining_seconds": int(record.blocked_until - current_time),
                        "failed_attempts": record.failed_attempts
                    })
        
        return blocked


# Global rate limiter instance - will be initialized with config
_rate_limiter: Optional[LoginRateLimiter] = None


def get_rate_limiter() -> LoginRateLimiter:
    """Get the global rate limiter instance"""
    global _rate_limiter
    if _rate_limiter is None:
        # Import here to avoid circular imports
        from miloco_server.config import RATE_LIMIT_CONFIG
        _rate_limiter = LoginRateLimiter(
            max_failed_attempts=RATE_LIMIT_CONFIG["max_failed_attempts"],
            block_duration_seconds=RATE_LIMIT_CONFIG["block_duration_seconds"],
            attempt_window_seconds=RATE_LIMIT_CONFIG["attempt_window_seconds"],
        )
    return _rate_limiter


def get_client_ip_from_request(request) -> str:
    """
    Extract client IP from FastAPI request
    Handles reverse proxy scenarios (X-Forwarded-For, X-Real-IP)
    
    Args:
        request: FastAPI Request object
        
    Returns:
        str: Client IP address
    """
    # Check X-Forwarded-For header (common for reverse proxies)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP (original client)
        return forwarded_for.split(",")[0].strip()
    
    # Check X-Real-IP header (used by nginx)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    # Fall back to direct client IP
    if request.client:
        return request.client.host
    
    return "unknown"

