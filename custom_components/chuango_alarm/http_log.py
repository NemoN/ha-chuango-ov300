from __future__ import annotations

import json
from typing import Any


SENSITIVE_KEYS = {
    "password",
    "token",
    "authorization",
    "cookie",
    "set-cookie",
}


def _redact_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    k = (key or "").lower()
    if k in SENSITIVE_KEYS:
        return "***"
    return value


def redact_mapping(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if data is None:
        return None
    out: dict[str, Any] = {}
    for k, v in data.items():
        out[k] = _redact_value(k, v)
    return out


def redact_headers(headers: dict[str, Any] | None) -> dict[str, Any] | None:
    if headers is None:
        return None
    out: dict[str, Any] = {}
    for k, v in headers.items():
        out[k] = _redact_value(k, v)
    return out


def truncate(text: str, limit: int = 6000) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [truncated {len(text) - limit} chars]"


def pretty_json(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:
        return str(obj)
