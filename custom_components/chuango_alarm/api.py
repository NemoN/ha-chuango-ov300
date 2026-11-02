from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import (
    ALARM_HISTORY_PATH,
    DEFAULT_APP,
    DEFAULT_APP_VER,
    DEFAULT_BRAND_HEADER,
    DEFAULT_LANG,
    DEFAULT_OS,
    DEFAULT_OS_VER,
    DEFAULT_PHONE_BRAND,
    DEFAULT_USER_AGENT,
    DEVICE_LIST_PATHS,
    FWINFO_PATH,
    LOGIN_PATH,
    ZONE_API_BASE,
    ZONE_PATH,
)
from .http_log import pretty_json, redact_headers, redact_mapping, truncate


class DreamcatcherError(Exception):
    pass


class DreamcatcherAuthError(DreamcatcherError):
    pass


class DreamcatcherApiError(DreamcatcherError):
    pass


@dataclass
class LoginResult:
    token: str
    expire_at: int
    user_info: dict[str, Any]


@dataclass
class ZoneResult:
    region: str
    am_domain: str
    am_ip: str
    am_port: int
    mqtt_domain: str
    mqtt_ip: str
    mqtt_port: int


class DreamcatcherApiClient:
    def __init__(self, session: aiohttp.ClientSession, logger: logging.Logger) -> None:
        self._session = session
        self._log = logger

    async def get_zone(self, region: str) -> ZoneResult:
        url = f"{ZONE_API_BASE}{ZONE_PATH}"

        params = {"region": region}

        headers = {
            "Appversion": DEFAULT_APP_VER,
            "Platform": DEFAULT_OS,
            "Lang": DEFAULT_LANG,
            "Brand": DEFAULT_BRAND_HEADER,
            "User-Agent": DEFAULT_USER_AGENT,
        }

        if self._log.isEnabledFor(logging.DEBUG):
            self._log.debug(
                "HTTP REQUEST %s %s\nparams=%s\nheaders=%s",
                "GET",
                url,
                pretty_json(redact_mapping(params)),
                pretty_json(redact_headers(headers)),
            )

        try:
            async with asyncio.timeout(20):
                resp = await self._session.get(url, params=params, headers=headers)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise DreamcatcherApiError(f"Zone connection error: {err}") from err

        async with resp:
            body_bytes = await resp.read()
            body_text = body_bytes.decode("utf-8", errors="replace")

            if self._log.isEnabledFor(logging.DEBUG):
                self._log.debug(
                    "HTTP RESPONSE %s %s\nstatus=%s\nresp_headers=%s\nbody=%s",
                    "GET",
                    str(resp.url),
                    resp.status,
                    pretty_json(redact_headers(dict(resp.headers))),
                    truncate(body_text),
                )

            if resp.status != 200:
                raise DreamcatcherApiError(
                    f"Zone HTTP {resp.status}: {truncate(body_text, 300)}"
                )

            try:
                data = json.loads(body_text)
            except Exception as err:
                raise DreamcatcherApiError(
                    f"Zone invalid JSON: {err} | body={truncate(body_text, 300)}"
                ) from err

        am = data.get("am") or {}
        mqtt = data.get("mqtt") or {}

        try:
            return ZoneResult(
                region=str(data.get("region") or region),
                am_domain=str(am["domain"]),
                am_ip=str(am.get("ip") or ""),
                am_port=int(am["port"]),
                mqtt_domain=str(mqtt["domain"]),
                mqtt_ip=str(mqtt.get("ip") or ""),
                mqtt_port=int(mqtt["port"]),
            )
        except Exception as err:
            raise DreamcatcherApiError(
                f"Unexpected zone response shape: {truncate(pretty_json(data), 800)}"
            ) from err

    async def login(
        self,
        *,
        am_domain: str,
        am_port: int,
        country_code: str,
        email: str,
        password_md5: str,
        uuid: str,
    ) -> LoginResult:
        url = f"https://{am_domain}:{am_port}{LOGIN_PATH}"

        params = {
            "countryCode": country_code,
            "name": email,
            "password": password_md5,
            "uuid": uuid,
            "os": DEFAULT_OS,
            "osVer": DEFAULT_OS_VER,
            "app": DEFAULT_APP,
            "appVer": DEFAULT_APP_VER,
            "phoneBrand": DEFAULT_PHONE_BRAND,
            "lang": DEFAULT_LANG,
        }

        headers = {
            "Appversion": DEFAULT_APP_VER,
            "Platform": DEFAULT_OS,
            "Lang": DEFAULT_LANG,
            "Brand": DEFAULT_BRAND_HEADER,
            "User-Agent": DEFAULT_USER_AGENT,
        }

        if self._log.isEnabledFor(logging.DEBUG):
            self._log.debug(
                "HTTP REQUEST %s %s\nparams=%s\nheaders=%s",
                "GET",
                url,
                pretty_json(redact_mapping(params)),
                pretty_json(redact_headers(headers)),
            )

        try:
            async with asyncio.timeout(20):
                resp = await self._session.get(url, params=params, headers=headers)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise DreamcatcherApiError(f"Connection error: {err}") from err

        async with resp:
            body_bytes = await resp.read()
            body_text = body_bytes.decode("utf-8", errors="replace")

            if self._log.isEnabledFor(logging.DEBUG):
                self._log.debug(
                    "HTTP RESPONSE %s %s\nstatus=%s\nresp_headers=%s\nbody=%s",
                    "GET",
                    str(resp.url),
                    resp.status,
                    pretty_json(redact_headers(dict(resp.headers))),
                    truncate(body_text),
                )

            if resp.status in (401, 403):
                raise DreamcatcherAuthError(
                    f"Auth failed ({resp.status}): {truncate(body_text, 300)}"
                )

            if resp.status != 200:
                raise DreamcatcherApiError(
                    f"HTTP {resp.status}: {truncate(body_text, 300)}"
                )

            try:
                data = json.loads(body_text)
            except Exception as err:
                raise DreamcatcherApiError(
                    f"Invalid JSON: {err} | body={truncate(body_text, 300)}"
                ) from err

        token = data.get("token")
        expire_at = data.get("expireAt")
        user_info = data.get("userInfo")

        if not token or not expire_at or not isinstance(user_info, dict):
            raise DreamcatcherApiError(
                f"Unexpected login response shape: {truncate(pretty_json(data), 500)}"
            )

        return LoginResult(token=token, expire_at=int(expire_at), user_info=user_info)

    async def shared_devices(
        self,
        *,
        am_domain: str,
        am_port: int,
        token: str,
    ) -> list[dict[str, Any]]:
        headers = {
            "Appversion": DEFAULT_APP_VER,
            "Platform": DEFAULT_OS,
            "Lang": DEFAULT_LANG,
            "Brand": DEFAULT_BRAND_HEADER,
            "User-Agent": DEFAULT_USER_AGENT,
        }

        params = {"token": token}
        last_data: dict[str, Any] | None = None

        for path in DEVICE_LIST_PATHS:
            url = f"https://{am_domain}:{am_port}{path}"

            if self._log.isEnabledFor(logging.DEBUG):
                self._log.debug(
                    "HTTP REQUEST %s %s\nparams=%s\nheaders=%s",
                    "GET",
                    url,
                    pretty_json(redact_mapping(params)),
                    pretty_json(redact_headers(headers)),
                )

            try:
                async with asyncio.timeout(20):
                    resp = await self._session.get(url, params=params, headers=headers)
            except (aiohttp.ClientError, TimeoutError):
                continue

            async with resp:
                body_bytes = await resp.read()
                body_text = body_bytes.decode("utf-8", errors="replace")

                if self._log.isEnabledFor(logging.DEBUG):
                    self._log.debug(
                        "HTTP RESPONSE %s %s\nstatus=%s\nresp_headers=%s\nbody=%s",
                        "GET",
                        str(resp.url),
                        resp.status,
                        pretty_json(redact_headers(dict(resp.headers))),
                        truncate(body_text),
                    )

                if resp.status in (401, 403):
                    raise DreamcatcherAuthError(
                        f"Auth failed ({resp.status}): {truncate(body_text, 300)}"
                    )

                if resp.status != 200:
                    continue

                try:
                    data = json.loads(body_text)
                except Exception:
                    continue

                if not isinstance(data, dict):
                    continue

                last_data = data

                if isinstance(data.get("list"), list) and data["list"]:
                    break

        data = last_data or {}

        if not data:
            return []

        if "list" not in data:
            raise DreamcatcherApiError(
                f"Unexpected devices response shape: {truncate(pretty_json(data), 500)}"
            )

        if not isinstance(data["list"], list):
            raise DreamcatcherApiError(
                f"Unexpected devices list response shape: {truncate(pretty_json(data), 500)}"
            )

        items = data["list"]
        shared_devices: list[dict[str, Any]] = []

        for sd in items:
            if not isinstance(sd, dict):
                continue

            shared_devices.append(
                {
                    "ID": sd.get("ID"),
                    "devIdInt": sd.get("devIdInt"),
                    "product_id": sd.get("product_id"),
                    "dtype": sd.get("dtype"),
                    "mpid": sd.get("mpid"),
                    "alias": sd.get("alias"),
                    "userAuth": sd.get("userAuth"),
                    "mqtt": sd.get("mqtt") or {},
                    "dm": sd.get("dm") or {},
                    "p2p": sd.get("p2p") or {},
                    "homeID": sd.get("homeID"),
                    "roomID": sd.get("roomID"),
                    "roomName": sd.get("roomName") or "",
                }
            )

        return shared_devices

    async def alarm_history(
        self,
        *,
        base_url: str,
        token: str,
        dev_id_int: int,
        offset: int = 0,
        page_size: int = 50,
    ) -> dict[str, Any]:
        url = f"{base_url}{ALARM_HISTORY_PATH}"
        params = {"token": token}
        body = {
            "devIdInt": dev_id_int,
            "offset": offset,
            "pageSize": page_size,
            "random": 0,
        }

        headers = {
            "Content-Type": "application/json",
            "Appversion": DEFAULT_APP_VER,
            "Platform": DEFAULT_OS,
            "Lang": DEFAULT_LANG,
            "Brand": DEFAULT_BRAND_HEADER,
            "User-Agent": DEFAULT_USER_AGENT,
        }

        if self._log.isEnabledFor(logging.DEBUG):
            self._log.debug(
                "HTTP REQUEST %s %s\nparams=%s\nbody=%s\nheaders=%s",
                "POST",
                url,
                pretty_json(redact_mapping(params)),
                pretty_json(body),
                pretty_json(redact_headers(headers)),
            )

        try:
            async with asyncio.timeout(20):
                resp = await self._session.post(url, params=params, json=body, headers=headers)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise DreamcatcherApiError(f"Alarm history connection error: {err}") from err

        async with resp:
            body_bytes = await resp.read()
            body_text = body_bytes.decode("utf-8", errors="replace")

            if self._log.isEnabledFor(logging.DEBUG):
                self._log.debug(
                    "HTTP RESPONSE %s %s\nstatus=%s\nresp_headers=%s\nbody=%s",
                    "POST",
                    str(resp.url),
                    resp.status,
                    pretty_json(redact_headers(dict(resp.headers))),
                    truncate(body_text),
                )

            if resp.status in (401, 403):
                raise DreamcatcherAuthError(
                    f"Auth failed ({resp.status}): {truncate(body_text, 300)}"
                )

            if resp.status != 200:
                raise DreamcatcherApiError(
                    f"HTTP {resp.status}: {truncate(body_text, 300)}"
                )

            try:
                data = json.loads(body_text)
            except Exception as err:
                raise DreamcatcherApiError(
                    f"Invalid JSON: {err} | body={truncate(body_text, 300)}"
                ) from err

        if not isinstance(data, dict):
            raise DreamcatcherApiError(
                f"Unexpected alarm history response: {truncate(body_text, 300)}"
            )

        return data

    async def firmware_info(
        self,
        *,
        base_url: str,
        token: str,
        device_id_int: int,
        wifi_version: str,
        mcu_version: str = "",
        gsm_version: str = "",
        gsm_model: str = "",
    ) -> dict[str, Any]:
        url = f"{base_url}{FWINFO_PATH}"
        params: dict[str, str] = {
            "token": token,
            "deviceID": str(device_id_int),
            "wifi": wifi_version or "",
            "mcu": mcu_version or "",
            "g_v": gsm_version or "",
            "g_m": gsm_model or "",
        }

        headers = {
            "Appversion": DEFAULT_APP_VER,
            "Platform": DEFAULT_OS,
            "Lang": DEFAULT_LANG,
            "Brand": DEFAULT_BRAND_HEADER,
            "User-Agent": DEFAULT_USER_AGENT,
        }

        if self._log.isEnabledFor(logging.DEBUG):
            self._log.debug(
                "HTTP REQUEST %s %s\nparams=%s\nheaders=%s",
                "GET",
                url,
                pretty_json(redact_mapping(params)),
                pretty_json(redact_headers(headers)),
            )

        try:
            async with asyncio.timeout(20):
                resp = await self._session.get(url, params=params, headers=headers)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise DreamcatcherApiError(f"Firmware info connection error: {err}") from err

        async with resp:
            body_bytes = await resp.read()
            body_text = body_bytes.decode("utf-8", errors="replace")

            if self._log.isEnabledFor(logging.DEBUG):
                self._log.debug(
                    "HTTP RESPONSE %s %s\nstatus=%s\nresp_headers=%s\nbody=%s",
                    "GET",
                    str(resp.url),
                    resp.status,
                    pretty_json(redact_headers(dict(resp.headers))),
                    truncate(body_text),
                )

            if resp.status in (401, 403):
                raise DreamcatcherAuthError(
                    f"Auth failed ({resp.status}): {truncate(body_text, 300)}"
                )

            if resp.status != 200:
                raise DreamcatcherApiError(
                    f"HTTP {resp.status}: {truncate(body_text, 300)}"
                )

            try:
                data = json.loads(body_text)
            except Exception as err:
                raise DreamcatcherApiError(
                    f"Invalid JSON: {err} | body={truncate(body_text, 300)}"
                ) from err

        if not isinstance(data, dict):
            raise DreamcatcherApiError(
                f"Unexpected fwinfo response: {truncate(body_text, 300)}"
            )

        return data