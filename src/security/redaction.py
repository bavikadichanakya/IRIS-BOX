import re
import copy
from typing import Any, Dict, List, Union

# Regex patterns for matching common credentials in plain strings
SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_\-]{20,}", re.IGNORECASE),
    re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{15,}", re.IGNORECASE),
    re.compile(r"key-[a-zA-Z0-9_\-]{20,}", re.IGNORECASE),
    re.compile(r"eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}", re.IGNORECASE),
]

SENSITIVE_KEY_PATTERNS = re.compile(
    r"(password|passcode|token|secret|api_key|apikey|authorization|auth|private_key|access_token|refresh_token|credential)",
    re.IGNORECASE,
)


def redact_string(val: str) -> str:
    """Mask sensitive string patterns within a raw text string."""
    if not isinstance(val, str):
        return val

    redacted = val
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def redact_sensitive_data(data: Any, max_depth: int = 10) -> Any:
    """
    Recursively scans and redacts sensitive keys and values from dicts, lists, tuples, and strings.
    Returns a copy with redacted values to avoid mutating inputs.
    """
    if max_depth <= 0:
        return data

    if isinstance(data, str):
        return redact_string(data)

    if isinstance(data, dict):
        new_dict = {}
        for k, v in data.items():
            str_key = str(k)
            if SENSITIVE_KEY_PATTERNS.search(str_key):
                new_dict[k] = "[REDACTED]"
            else:
                new_dict[k] = redact_sensitive_data(v, max_depth - 1)
        return new_dict

    if isinstance(data, list):
        return [redact_sensitive_data(item, max_depth - 1) for item in data]

    if isinstance(data, tuple):
        return tuple(redact_sensitive_data(item, max_depth - 1) for item in data)

    if isinstance(data, set):
        return {redact_sensitive_data(item, max_depth - 1) for item in data}

    if hasattr(data, "model_dump") and callable(data.model_dump):
        try:
            dumped = data.model_dump()
            return redact_sensitive_data(dumped, max_depth - 1)
        except Exception:
            pass

    return data
