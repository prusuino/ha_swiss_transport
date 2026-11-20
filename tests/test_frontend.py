"""Serving of the bundled card: registered once per run, without the
optional files when they are missing, and tried again after a failure."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.swiss_transport.const import DOMAIN
from custom_components.swiss_transport.frontend import CARD_URL_BASE, async_serve_card


@pytest.fixture
async def http(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "http", {})


async def test_card_is_registered_once_per_run(hass: HomeAssistant, http) -> None:
    with patch.object(hass.http, "async_register_static_paths") as register:
        await async_serve_card(hass, "1.0.0")
        await async_serve_card(hass, "1.0.0")
    register.assert_awaited_once()
    paths = {config.url_path: config for config in register.await_args.args[0]}
    assert set(paths) == {
        CARD_URL_BASE,
        f"/{DOMAIN}_files/mode-train.svg",
        f"/{DOMAIN}_files/mode-tram.svg",
        f"/{DOMAIN}_files/mode-bus.svg",
        f"/{DOMAIN}_files/mode-ship.svg",
        f"/{DOMAIN}_files/mode-cableway.svg",
        f"/{DOMAIN}_files/line-colors.json",
    }
    assert Path(paths[CARD_URL_BASE].path).name == "swiss-transport-card.js"
    assert all(config.cache_headers is False for config in paths.values())


async def test_missing_icons_and_colours_are_left_out(hass: HomeAssistant, http, hass_client) -> None:
    with patch.object(Path, "is_file", return_value=False):
        await async_serve_card(hass, "1.0.0")
    client = await hass_client()
    assert (await client.get(CARD_URL_BASE)).status == 200
    assert (await client.get(f"/{DOMAIN}_files/mode-train.svg")).status == 404
    assert (await client.get(f"/{DOMAIN}_files/line-colors.json")).status == 404


async def test_failed_registration_is_tried_again_next_time(hass: HomeAssistant, http, hass_client) -> None:
    with (
        patch.object(hass.http, "async_register_static_paths", side_effect=RuntimeError("server not ready")),
        pytest.raises(RuntimeError),
    ):
        await async_serve_card(hass, "1.0.0")
    await async_serve_card(hass, "1.0.0")
    client = await hass_client()
    assert (await client.get(CARD_URL_BASE)).status == 200
