import os
import sys
import pytest
import socket

# Add the project root to sys.path
# This allows imports like 'from src.models.schemas import ...' to work
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
)


@pytest.fixture(autouse=True)
def network_guard(monkeypatch):
    """
    Air-gapped network guard: Intercepts socket connection attempts and fails
    if an outbound connection outside loopback (127.0.0.1, ::1, localhost) is attempted.
    """
    orig_connect = socket.socket.connect

    def guarded_connect(self, address):
        try:
            if isinstance(address, tuple) and len(address) >= 2:
                host = str(address[0])
                allowed = ("127.0.0.1", "::1", "localhost", "0.0.0.0", "", "localhost.localdomain")
                if host and not (any(host == a or host.startswith("127.") for a in allowed) or host.startswith("\\")):
                    raise RuntimeError(
                        f"Forbidden outbound network connection attempted to {host}:{address[1]} outside loopback."
                    )
        except RuntimeError:
            raise
        except Exception:
            pass
        return orig_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
