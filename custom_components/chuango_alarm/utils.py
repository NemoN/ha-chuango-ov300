from __future__ import annotations

import hashlib
import random
import time


PRODUCT_ID_LABELS: dict[str, str] = {
    "3": "OV-300 Hub",
    "19": "OV-300 V2 Hub",
    "300": "OV-300 V2 Hub (Variant 300)",
    "5": "LTE-400 Hub",
    "22": "LTE-400 Hub (Variant 22)",
    "38": "LTE-400 Hub (Variant 38)",
    "42": "G5-LTE Alarm",
}

DTYPE_LABELS: dict[str, str] = {
    "SA": "Security Alarm",
}

PART_MD_LABELS: dict[int, str] = {
    0: "restricted",
    1: "normal",
}


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


def product_name_from_id(product_id: str | int | None) -> str | None:
    if product_id is None:
        return None
    return PRODUCT_ID_LABELS.get(str(product_id))


def dtype_name(dtype: str | None) -> str | None:
    if dtype is None:
        return None
    return DTYPE_LABELS.get(str(dtype))


def format_product_id_value(product_id: str | int | None) -> str | None:
    if product_id is None:
        return None
    raw = str(product_id)
    label = product_name_from_id(raw)
    return f"{raw} ({label})" if label else raw


def format_dtype_value(dtype: str | None) -> str | None:
    if dtype is None:
        return None
    raw = str(dtype)
    label = dtype_name(raw)
    return f"{raw} ({label})" if label else raw


def resolve_device_model(dtype: str | None, product_id: str | int | None) -> str | None:
    """Return a human-readable model for HA DeviceInfo.

    Prefer product-id model names when known, then dtype label, then raw dtype.
    """
    product_label = product_name_from_id(product_id)
    if product_label:
        return product_label

    dtype_label = dtype_name(dtype)
    if dtype_label:
        return dtype_label

    if dtype:
        return str(dtype)

    return None


def part_md_label(md: int | None) -> str:
    if md is None:
        return "unknown"
    return PART_MD_LABELS.get(md, f"unknown_{md}")


def part_zone_change_allowed(md: int | None, zone: int | None) -> bool:
    """Return whether zone change should be allowed for a part.

    APK behavior in AccessSetActivity:
    - if current zone is 0 and md == 0 -> zone editing disabled
    - otherwise allowed
    """
    return not (zone == 0 and md == 0)
