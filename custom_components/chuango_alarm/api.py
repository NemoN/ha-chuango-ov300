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

    async def get_zone(self, region: str, lang: str = DEFAULT_LANG) -> ZoneResult:
        url = f"{ZONE_API_BASE}{ZONE_PATH}"

        params = {"region": region}

        headers = {
            "Appversion": DEFAULT_APP_VER,
            "Platform": DEFAULT_OS,
            "Lang": lang,
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
        os: str = DEFAULT_OS,
        os_ver: str = DEFAULT_OS_VER,
        app: str = DEFAULT_APP,
        app_ver: str = DEFAULT_APP_VER,
        phone_brand: str = DEFAULT_PHONE_BRAND,
        lang: str = DEFAULT_LANG,
    ) -> LoginResult:
        url = f"https://{am_domain}:{am_port}{LOGIN_PATH}"

        params = {
            "countryCode": country_code,
            "name": email,
            "password": password_md5,
            "os": os,
            "osVer": os_ver,
            "app": app,
            "appVer": app_ver,
            "phoneBrand": phone_brand,
            "uuid": uuid,
            "lang": lang,
        }

        headers = {
            "Appversion": app_ver,
            "Platform": os,
            "Lang": lang,
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
            raise DreamcatcherApiError(f"Login connection error: {err}") from err

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
