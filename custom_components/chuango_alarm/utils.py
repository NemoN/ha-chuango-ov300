from __future__ import annotations

import hashlib
import random
import time


def md5_hex(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def looks_like_md5(value: str) -> bool:
    if len(value) != 32:
        return False
    try:
        int(value, 16)
        return True
    except ValueError:
        return False


def generate_vendor_uuid() -> str:
    ts_ms = int(time.time() * 1000)
    rnd = random.randint(0, 999999)
    return f"uuid_{ts_ms}_{rnd:06d}"
