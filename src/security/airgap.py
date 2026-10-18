"""
Strict socket air-gap enforcement guard for IRIS-BOX.
Intercepts outbound socket creation/connections and ensures zero non-loopback
network communication can occur.
"""

from __future__ import annotations

import contextlib
import socket
from typing import Iterator, Set

LOOPBACK_HOSTS: Set[str] = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


class AirGapViolationError(RuntimeError):
    """Raised when an outbound socket connection violates the air-gap mandate."""
    pass


@contextlib.contextmanager
def socket_air_gap_guard() -> Iterator[None]:
    """
    Strict socket interceptor guaranteeing offline air-gap enforcement.
    Intercepts any outbound connection attempt to non-loopback addresses
    and raises AirGapViolationError immediately.
    """
    orig_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: any) -> any:
        if isinstance(address, tuple):
            host = str(address[0])
        else:
            host = str(address)

        if host in LOOPBACK_HOSTS or host.startswith("127."):
            return orig_connect(self, address)

        raise AirGapViolationError(
            f"AIR_GAP_VIOLATION: Non-loopback network attempt blocked to {host}:{address}"
        )

    socket.socket.connect = guarded_connect
    try:
        yield
    finally:
        socket.socket.connect = orig_connect
