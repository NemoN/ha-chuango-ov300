from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector

from .api import DreamcatcherApiClient, DreamcatcherAuthError, DreamcatcherError
from .const import (
    DOMAIN,
    CONF_COUNTRY_CODE,
    CONF_EMAIL,
    CONF_PASSWORD,
    DEFAULT_COUNTRY_CODE,
    DEFAULT_OS,
    DEFAULT_OS_VER,
    DEFAULT_APP,
    DEFAULT_APP_VER,
    DEFAULT_PHONE_BRAND,
    DEFAULT_LANG,
)
from .utils import generate_vendor_uuid, md5_hex, looks_like_md5

_LOGGER = logging.getLogger(__name__)


class DreamcatcherConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            country_code = user_input[CONF_COUNTRY_CODE].strip()
            email = user_input[CONF_EMAIL].strip()

            pw_raw = user_input[CONF_PASSWORD].strip()
            password_md5 = pw_raw if looks_like_md5(pw_raw) else md5_hex(pw_raw)

            uuid = generate_vendor_uuid()

            session = async_get_clientsession(self.hass)
            api = DreamcatcherApiClient(session=session, logger=_LOGGER)

            try:
                res = await api.login(
                    country_code=country_code,
                    email=email,
                    password_md5=password_md5,
                    uuid=uuid,
                    os=DEFAULT_OS,
                    os_ver=DEFAULT_OS_VER,
                    app=DEFAULT_APP,
                    app_ver=DEFAULT_APP_VER,
                    phone_brand=DEFAULT_PHONE_BRAND,
                    lang=DEFAULT_LANG,
                )
            except DreamcatcherAuthError:
                errors["base"] = "invalid_auth"
            except DreamcatcherError:
                errors["base"] = "cannot_connect"
            else:
                user_id = str(res.user_info.get("userId", ""))
                alias = str(res.user_info.get("alias", "")) or email

                await self.async_set_unique_id(user_id or email)
                self._abort_if_unique_id_configured()

                data = {
                    "country_code": country_code,
                    "email": email,
                    "password_md5": password_md5,
                    "uuid": uuid,
                    "os": DEFAULT_OS,
                    "os_ver": DEFAULT_OS_VER,
                    "app": DEFAULT_APP,
                    "app_ver": DEFAULT_APP_VER,
                    "phone_brand": DEFAULT_PHONE_BRAND,
                    "lang": DEFAULT_LANG,
                }

                return self.async_create_entry(title=alias, data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_COUNTRY_CODE, default=DEFAULT_COUNTRY_CODE): str,
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
