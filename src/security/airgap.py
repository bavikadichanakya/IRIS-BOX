"""
Strict socket air-gap enforcement guard for IRIS-BOX.
Intercepts outbound socket creation and connections to ensure non-loopback
network communication is rejected at the Python runtime boundary.
"""

from __future__ import annotations

import contextlib
import socket
import ipaddress
import logging
from typing import Iterator, Set

logger = logging.getLogger("iris.security.airgap")

LOOPBACK_HOSTS: Set[str] = {"127.0.0.1", "localhost", "::1"}


class AirGapViolationError(RuntimeError):
    """Raised when an outbound socket connection violates the air-gap mandate."""
    pass


def is_loopback_destination(host: str) -> bool:
    """
    Validates whether a target host string is strictly a loopback address.
    Rejects wildcard addresses (0.0.0.0), non-loopback LAN addresses, and
    malicious hostnames like '127.evil.com'.
    """
    clean_host = (host or "").strip().lower()
    if clean_host in LOOPBACK_HOSTS:
        return True

    # Validate against strict IPv4 / IPv6 loopback addresses (127.0.0.0/8, ::1)
    try:
        ip = ipaddress.ip_address(clean_host)
        return ip.is_loopback
    except ValueError:
        # Not a raw IP address (could be a hostname)
        pass

    return False


@contextlib.contextmanager
def socket_air_gap_guard() -> Iterator[None]:
    """
    Socket interceptor providing application-level defense-in-depth against outbound egress.
    Intercepts any connect() or connect_ex() call to non-loopback addresses
    and raises AirGapViolationError.
    """
    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex

    def _extract_host(address: any) -> str:
        if isinstance(address, tuple) and len(address) > 0:
            return str(address[0])
        return str(address)

    def guarded_connect(self: socket.socket, address: any) -> any:
        host = _extract_host(address)
        if is_loopback_destination(host):
            return orig_connect(self, address)

        logger.critical(f"AIR_GAP_VIOLATION: Blocked outbound connection attempt to non-loopback destination '{host}'")
        raise AirGapViolationError(
            f"AIR_GAP_VIOLATION: Non-loopback network attempt blocked to {host}:{address}"
        )

    def guarded_connect_ex(self: socket.socket, address: any) -> int:
        host = _extract_host(address)
        if is_loopback_destination(host):
            return orig_connect_ex(self, address)

        logger.critical(f"AIR_GAP_VIOLATION: Blocked connect_ex attempt to non-loopback destination '{host}'")
        raise AirGapViolationError(
            f"AIR_GAP_VIOLATION: Non-loopback network attempt blocked to {host}:{address}"
        )

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    try:
        yield
    finally:
        socket.socket.connect = orig_connect
        socket.socket.connect_ex = orig_connect_ex
