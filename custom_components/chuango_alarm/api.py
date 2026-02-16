from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import (
    DEFAULT_APP,
    DEFAULT_APP_VER,
    DEFAULT_BRAND_HEADER,
    DEFAULT_LANG,
    DEFAULT_OS,
    DEFAULT_OS_VER,
    DEFAULT_PHONE_BRAND,
    DEFAULT_USER_AGENT,
    LOGIN_PATH,
    SHARED_DEVICES_PATH,
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

    async def get_zone(
            self,
            region: str,
    ) -> ZoneResult:
        url = f"{ZONE_API_BASE}{ZONE_PATH}"

        params = {
            "region": region
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
                raise DreamcatcherApiError(f"Zone HTTP {resp.status}: {truncate(body_text, 300)}")

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
            raise DreamcatcherApiError(f"Unexpected zone response shape: {truncate(pretty_json(data), 800)}") from err

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
                raise DreamcatcherAuthError(f"Auth failed ({resp.status}): {truncate(body_text, 300)}")

            if resp.status != 200:
                raise DreamcatcherApiError(f"HTTP {resp.status}: {truncate(body_text, 300)}")

            try:
                data = json.loads(body_text)
            except Exception as err:
                raise DreamcatcherApiError(f"Invalid JSON: {err} | body={truncate(body_text, 300)}") from err

        token = data.get("token")
        expire_at = data.get("expireAt")
        user_info = data.get("userInfo")

        if not token or not expire_at or not isinstance(user_info, dict):
            raise DreamcatcherApiError(f"Unexpected login response shape: {truncate(pretty_json(data), 500)}")

        return LoginResult(token=token, expire_at=int(expire_at), user_info=user_info)
    
    async def shared_devices(
            self,
            *,
            am_domain: str,
            am_port: int,
            token: str
    ) -> list[dict[str, Any]]:
        url = f"https://{am_domain}:{am_port}{SHARED_DEVICES_PATH}"
        params = {
            "token": token
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
                raise DreamcatcherAuthError(f"Auth failed ({resp.status}): {truncate(body_text, 300)}")
            
            if resp.status != 200:
                raise DreamcatcherApiError(f"HTTP {resp.status}: {truncate(body_text, 300)}")

            try:
                data = json.loads(body_text)
            except Exception as err:
                raise DreamcatcherApiError(f"Invalid JSON: {err} | body={truncate(body_text, 300)}") from err

        # Some accounts (or server variants) return an empty object instead of {"list": []}.
        # Treat that as "no shared devices" so the config flow can show a helpful message.
        if isinstance(data, dict) and not data:
            return []

        if not isinstance(data, dict) or "list" not in data or not isinstance(data["list"], list):
            raise DreamcatcherApiError(
                f"Unexpected shared devices response shape: {truncate(pretty_json(data), 500)}"
            )

        """ {
            "list": [
                {
                    "devIdInt": 110858,
                    "ID": "00001900000244212033",
                    "product_id": "19",
                    "dtype": "SA",
                    "mpid": "19",
                    "alias": "OV-300",
                    "userAuth": "general",
                    "mqtt": {
                        "domain": "psb1.iotdreamcatcher.net",
                        "ip": "52.28.65.29",
                        "port": 18883,
                        "token": "9ZalSwg5Xx44VA05gLdszjVvQM1RUQDbO_3920dr8K8"
                    },
                    "forceUpdate": 0,
                    "p2p": {
                        "domain": "psb1.iotdreamcatcher.net",
                        "ip": "52.28.65.29",
                        "port": 10005
                    },
                    "dm": {
                        "domain": "psb1.iotdreamcatcher.net",
                        "ip": "52.28.65.29",
                        "port": 12443
                    },
                    "homeID": 0,
                    "roomID": 0,
                    "roomName": "",
                    "pushEn": 1,
                    "wxPushEn": 1,
                    "hmodePushEn": 1,
                    "tempPushEn": 1,
                    "humPushEn": 1,
                    "illumPushEn": 1,
                    "smokeSoundPushEn": 1,
                    "pirPushEn": 1,
                    "soundSrc": "",
                    "utype": 0,
                    "ble": {},
                    "parentId": ""
                }
            ]
        }
        """

        items = data["list"]
        shared_devices: list[dict[str, Any]] = []
        for sd in items:
            if not isinstance(sd, dict):
                continue
            shared_devices.append({
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
            })

        return shared_devices
