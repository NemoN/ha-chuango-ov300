from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector

from .api import DreamcatcherApiClient, DreamcatcherAuthError, DreamcatcherError
from .const import (
    CONF_AM_DOMAIN,
    CONF_AM_IP,
    CONF_AM_PORT,
    CONF_COUNTRY_CODE,
    CONF_COUNTRY_NAME,
    CONF_EMAIL,
    CONF_PASSWORD_MD5,
    CONF_MQTT_DOMAIN,
    CONF_MQTT_IP,
    CONF_MQTT_PORT,
    CONF_REGION,
    CONF_UUID,
    DOMAIN,
)
from .countries_data import COUNTRIES, LOCALE_TO_COUNTRY
from .utils import generate_vendor_uuid, md5_hex, looks_like_md5

_LOGGER = logging.getLogger(__name__)


class DreamcatcherConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        countries = COUNTRIES

        def _valid_locale(loc: str | None) -> bool:
            if not loc:
                return False
            loc = str(loc).strip()
            return len(loc) == 2 and loc.isalpha() and loc.isupper()

        options = [
            selector.SelectOptionDict(
                value=str(c["locale"]),
                label=f"{c['en']} (+{c['code']})",
            )
            for c in countries
            if _valid_locale(c.get("locale")) and c.get("en") and c.get("code")
        ]

        default_region = "DE" if any(str(c.get("locale")) == "DE" for c in countries) else None
        default_email: str = ""

        if user_input is not None:
            default_region = str(user_input.get(CONF_REGION) or default_region or "").strip() or default_region
            default_email = str(user_input.get(CONF_EMAIL) or "").strip()

        schema = vol.Schema(
            {
                vol.Required(CONF_REGION, default=default_region): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        sort=True,
                    )
                ),
                vol.Required(CONF_EMAIL, default=default_email): str,
                vol.Required("password"): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }
        )

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

        region = str(user_input[CONF_REGION]).strip()
        email = str(user_input[CONF_EMAIL]).strip()
        pw_raw = str(user_input["password"]).strip()

        country = LOCALE_TO_COUNTRY.get(region)
        if not country:
            errors["base"] = "invalid_region"
            return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

        country_name = str(country.get("en") or region)
        country_code = f"+{country['code']}"

        password_md5 = pw_raw if looks_like_md5(pw_raw) else md5_hex(pw_raw)
        uuid = getattr(self, "_vendor_uuid", None) or generate_vendor_uuid()
        self._vendor_uuid = uuid

        session = async_get_clientsession(self.hass)
        api = DreamcatcherApiClient(session=session, logger=_LOGGER)

        try:
            zone = await api.get_zone(
                region=region
            )

            res = await api.login(
                am_domain=zone.am_domain,
                am_port=zone.am_port,
                country_code=country_code,
                email=email,
                password_md5=password_md5,
                uuid=uuid,
            )

            shared = await api.shared_devices(
                am_domain=zone.am_domain,
                am_port=zone.am_port,
                token=res.token,
            )
            if not shared:
                errors["base"] = "no_shared_devices"
                return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
        except DreamcatcherAuthError:
            errors["base"] = "invalid_auth"
            return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
        except DreamcatcherError:
            errors["base"] = "cannot_connect"
            return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

        user_id = str(res.user_info.get("userId", ""))
        alias = str(res.user_info.get("alias", "")) or email

        await self.async_set_unique_id(user_id or email)
        self._abort_if_unique_id_configured()

        data = {
            CONF_REGION: region,
            CONF_COUNTRY_NAME: country_name,
            CONF_COUNTRY_CODE: country_code,
            CONF_EMAIL: email,
            CONF_PASSWORD_MD5: password_md5,
            CONF_UUID: uuid,
            CONF_AM_DOMAIN: zone.am_domain,
            CONF_AM_IP: zone.am_ip,
            CONF_AM_PORT: zone.am_port,
            CONF_MQTT_DOMAIN: zone.mqtt_domain,
            CONF_MQTT_IP: zone.mqtt_ip,
            CONF_MQTT_PORT: zone.mqtt_port,
        }

        return self.async_create_entry(title=alias, data=data)
