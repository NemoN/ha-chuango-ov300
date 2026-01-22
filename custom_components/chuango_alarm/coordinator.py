from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import DreamcatcherApiClient, DreamcatcherAuthError, DreamcatcherError
from .const import (
    CONF_AM_DOMAIN,
    CONF_AM_PORT,
    CONF_COUNTRY_CODE,
    CONF_EMAIL,
    CONF_PASSWORD_MD5,
    CONF_UUID,
    DOMAIN,
)


class DreamcatcherCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        api: DreamcatcherApiClient,
        entry_data: dict[str, Any],
        logger: logging.Logger,
    ) -> None:
        super().__init__(
            hass,
            logger,
            name=DOMAIN,
            update_interval=timedelta(hours=6),
        )
        self.api = api
        self.entry_data = entry_data
        self.token: str | None = None
        self.expire_at: int | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            res = await self.api.login(
                am_domain=self.entry_data[CONF_AM_DOMAIN],
                am_port=int(self.entry_data[CONF_AM_PORT]),
                country_code=self.entry_data[CONF_COUNTRY_CODE],
                email=self.entry_data[CONF_EMAIL],
                password_md5=self.entry_data[CONF_PASSWORD_MD5],
                uuid=self.entry_data[CONF_UUID],
                os=self.entry_data.get("os"),
                os_ver=self.entry_data.get("os_ver"),
                app=self.entry_data.get("app"),
                app_ver=self.entry_data.get("app_ver"),
                phone_brand=self.entry_data.get("phone_brand"),
                lang=self.entry_data.get("lang"),
            )
        except DreamcatcherAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except DreamcatcherError as err:
            raise UpdateFailed(f"Update failed: {err}") from err

        self.token = res.token
        self.expire_at = res.expire_at

        return {
            "userInfo": res.user_info,
            "expireAt": res.expire_at,
            "lastLogin": dt_util.utcnow().isoformat(),
        }
