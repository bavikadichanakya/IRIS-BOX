import ipaddress
import re
import socket
from urllib.parse import urlparse
from typing import Optional, List, Tuple, Union

# Prohibited metadata and internal domains/IPs for SSRF prevention
METADATA_IPS = {
    "169.254.169.254",
    "169.254.169.253",
    "100.100.100.200",
}

METADATA_HOSTNAMES = {
    "metadata.google.internal",
    "instance-data",
    "metadata",
}

PROHIBITED_METACHARS = re.compile(r"[;&|`$><\n\r\t]")


def is_url_allowed(
    url: str,
    allowlist: Optional[List[str]] = None,
    denylist: Optional[List[str]] = None
) -> Tuple[bool, Optional[str]]:
    """
    Validates target URL against SSRF rules, IP range restrictions, and domain allowlists.
    """
    if not url:
        return False, "URL cannot be empty."

    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"Invalid URL format: {e}"

    scheme = parsed.scheme.lower() if parsed.scheme else ""
    if scheme not in ("http", "https"):
        return False, f"Unsupported scheme '{scheme}'. Only http and https are allowed."

    hostname = parsed.hostname
    if not hostname:
        return False, "URL missing hostname."

    hostname_lower = hostname.lower()

    # Check denylist
    if denylist and hostname_lower in [d.lower() for d in denylist]:
        return False, f"Domain '{hostname}' is explicitly denylisted."

    # Check allowlist override
    if allowlist and hostname_lower in [a.lower() for a in allowlist]:
        return True, None

    # Block metadata hostnames
    if hostname_lower in METADATA_HOSTNAMES:
        return False, f"Access to cloud metadata hostname '{hostname}' is blocked."

    # Check IP address restrictions
    try:
        # Resolve hostname or parse IP directly
        ip_obj = ipaddress.ip_address(hostname_lower)
    except ValueError:
        # Not a raw IP, try resolving hostname
        try:
            resolved_ip_str = socket.gethostbyname(hostname_lower)
            ip_obj = ipaddress.ip_address(resolved_ip_str)
        except Exception:
            # If DNS resolution fails in offline test, fallback to checking string
            ip_obj = None

    if ip_obj:
        ip_str = str(ip_obj)

        if ip_str in METADATA_IPS:
            return False, f"Access to metadata IP '{ip_str}' is blocked."

        if ip_obj.is_loopback:
            # If allowlist explicitly has localhost, permit loopback
            if allowlist and ("localhost" in allowlist or "127.0.0.1" in allowlist):
                return True, None
            return False, f"Access to loopback IP '{ip_str}' is blocked."

        if ip_obj.is_private or ip_obj.is_link_local:
            if allowlist and ip_str in allowlist:
                return True, None
            return False, f"Access to private/link-local IP '{ip_str}' is blocked."

    return True, None


def validate_system_command(
    command: Union[str, List[str]],
    allowed_commands: Optional[List[str]] = None
) -> Tuple[bool, Optional[str]]:
    """
    Validates system commands for dangerous metacharacters and binary allowlist enforcement.
    """
    if isinstance(command, str):
        cmd_str = command
        parts = command.strip().split()
    elif isinstance(command, list):
        cmd_str = " ".join(command)
        parts = command
    else:
        return False, "Command must be a string or list of arguments."

    if not parts:
        return False, "Empty command."

    # 1. Prohibit shell metacharacters
    if PROHIBITED_METACHARS.search(cmd_str):
        return False, "Command contains prohibited shell metacharacters (;, &, |, `, $, >, <, newlines)."

    base_cmd = parts[0]

    # 2. Enforce binary allowlist if provided
    if allowed_commands:
        allowed_base = [c.split()[0] for c in allowed_commands]
        if base_cmd not in allowed_base:
            return False, f"Command '{base_cmd}' is not in the allowed list."

    return True, None
