"""Tests for Dreamcatcher device discovery and endpoint fallback."""

import json
import logging
import unittest
from unittest.mock import AsyncMock, Mock

import aiohttp

from custom_components.chuango_alarm.api import (
    DreamcatcherApiClient,
    DreamcatcherApiError,
    DreamcatcherAuthError,
)


class Response:
    def __init__(self, status=200, data=None, body=None):
        self.status = status
        self.body = body if body is not None else json.dumps(data).encode()
        self.url = "https://example.test/devices"
        self.headers = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def read(self):
        return self.body


class DeviceDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def discover(self, responses):
        session = Mock()
        session.get = AsyncMock(side_effect=responses)
        api = DreamcatcherApiClient(session, logging.getLogger(__name__))
        result = await api.shared_devices(am_domain="example.test", am_port=443, token="token")
        return result, session.get.call_count

    async def test_shared_devices_are_used_first(self):
        result, calls = await self.discover([Response(data={"list": [{"ID": "shared"}]})])
        self.assertEqual(result[0]["ID"], "shared")
        self.assertEqual(calls, 1)

    async def test_empty_shared_list_falls_back_to_owned_devices(self):
        result, calls = await self.discover([
            Response(data={"list": []}),
            Response(data={"list": [{"ID": "owned"}]}),
        ])
        self.assertEqual(result[0]["ID"], "owned")
        self.assertEqual(calls, 2)

    async def test_empty_list_and_unsupported_endpoints(self):
        result, _ = await self.discover([
            Response(data={"list": []}), Response(403), Response(404), Response(405),
        ])
        self.assertEqual(result, [])

    async def test_all_connection_errors_are_not_an_empty_list(self):
        with self.assertRaises(DreamcatcherApiError):
            await self.discover([aiohttp.ClientConnectionError("offline")] * 4)

    async def test_server_error_after_empty_list_is_not_silenced(self):
        with self.assertRaises(DreamcatcherApiError):
            await self.discover([
                Response(data={"list": []}), Response(500), Response(404), Response(404),
            ])

    async def test_invalid_json_is_not_an_empty_list(self):
        with self.assertRaises(DreamcatcherApiError):
            await self.discover([Response(body=b"invalid"), Response(404), Response(404), Response(404)])

    async def test_primary_authentication_error(self):
        for status in (401, 403):
            with self.subTest(status=status), self.assertRaises(DreamcatcherAuthError):
                await self.discover([Response(status)])

    async def test_fallback_unauthorized_is_authentication_error(self):
        with self.assertRaises(DreamcatcherAuthError):
            await self.discover([Response(data={"list": []}), Response(401)])

    async def test_later_valid_endpoint_recovers_from_error(self):
        result, _ = await self.discover([
            aiohttp.ClientConnectionError("offline"),
            Response(data={"list": [{"ID": "owned"}]}),
        ])
        self.assertEqual(result[0]["ID"], "owned")

    async def test_no_supported_endpoint_is_an_error(self):
        with self.assertRaises(DreamcatcherApiError):
            await self.discover([Response(404)] * 4)


if __name__ == "__main__":
    unittest.main()
