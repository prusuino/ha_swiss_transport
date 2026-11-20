"""Setting an entry up and unloading it again: the entities, the actions,
the bundled card over HTTP, a retry while the timetable API is down and the
refresh after an options change."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.swiss_transport.const import (
    CONF_LIMIT,
    CONTROLS_OWNER,
    DOMAIN,
    MODE_ENTITY_ID,
    TIME_ENTITY_ID,
)
from custom_components.swiss_transport.frontend import CARD_URL_BASE

from .common import (
    BOARD_ENTITY,
    BOARD_URL,
    CONNECTIONS_URL,
    ROUTE_ENTITY,
    FakeApi,
    add_board,
    add_connection,
    poll,
    setup,
    state_time,
)


async def test_board_entry_sets_up_and_unloads(hass: HomeAssistant, api: FakeApi) -> None:
    entry = await setup(hass, add_board(hass))
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(BOARD_ENTITY).state == state_time(4)
    assert hass.services.has_service(DOMAIN, "get_departures")
    assert hass.services.has_service(DOMAIN, "get_connections")
    assert hass.data[CONTROLS_OWNER] == entry.entry_id

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get(BOARD_ENTITY).state == STATE_UNAVAILABLE
    assert CONTROLS_OWNER not in hass.data


async def test_connection_entry_sets_up_and_unloads(hass: HomeAssistant, api: FakeApi) -> None:
    entry = await setup(hass, add_connection(hass))
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(ROUTE_ENTITY).state == state_time(6)
    assert len(api.requests(CONNECTIONS_URL)) == 1
    assert api.requests(BOARD_URL) == []

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ROUTE_ENTITY).state == STATE_UNAVAILABLE


async def test_setup_is_retried_while_the_timetable_api_is_down(hass: HomeAssistant, api: FakeApi) -> None:
    api.fail["board"] = 503
    entry = add_board(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert hass.states.get(BOARD_ENTITY) is None


async def test_unloading_keeps_the_controls_of_the_entry_that_owns_them(hass: HomeAssistant, api: FakeApi) -> None:
    owner = await setup(hass, add_board(hass))
    other = await setup(hass, add_connection(hass))
    assert await hass.config_entries.async_unload(other.entry_id)
    await hass.async_block_till_done()
    assert hass.data[CONTROLS_OWNER] == owner.entry_id
    assert hass.states.get(TIME_ENTITY_ID).state != STATE_UNAVAILABLE
    assert hass.states.get(MODE_ENTITY_ID).state == "live"


async def test_unloading_withdraws_the_repair_issue_of_the_entry(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    entry = await setup(hass, add_board(hass))
    api.fail["board"] = 500
    for _ in range(3):
        await poll(hass, freezer)
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, f"unreachable_{entry.entry_id}") is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, f"unreachable_{entry.entry_id}") is None


async def test_changed_options_refresh_the_board(hass: HomeAssistant, api: FakeApi) -> None:
    entry = await setup(hass, add_board(hass))
    assert len(api.requests(BOARD_URL)) == 1
    hass.config_entries.async_update_entry(entry, options={CONF_LIMIT: 3})
    await hass.async_block_till_done()
    requests = api.requests(BOARD_URL)
    assert len(requests) == 2
    assert requests[-1][1].query["limit"] == "3"
    assert hass.states.get(BOARD_ENTITY).attributes["limit"] == 3


async def test_card_and_its_files_are_served(hass: HomeAssistant, api: FakeApi, hass_client) -> None:
    await setup(hass, add_board(hass))
    await setup(hass, add_connection(hass))
    client = await hass_client()
    card = await client.get(CARD_URL_BASE)
    assert card.status == 200
    assert "customElements.define" in await card.text()
    assert "Cache-Control" not in card.headers
    for name in ("mode-train.svg", "mode-tram.svg", "mode-bus.svg", "mode-ship.svg", "mode-cableway.svg", "line-colors.json"):
        assert (await client.get(f"/{DOMAIN}_files/{name}")).status == 200, name


async def test_a_card_that_cannot_be_served_does_not_block_the_setup(hass: HomeAssistant, api: FakeApi, caplog) -> None:
    with patch("custom_components.swiss_transport.async_serve_card", side_effect=RuntimeError("no http")):
        entry = await setup(hass, add_board(hass))
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(BOARD_ENTITY).state == state_time(4)
    assert "Serving the bundled Lovelace card failed" in caplog.text


async def test_entry_that_does_not_unload_keeps_its_issues_and_the_controls(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    entry = await setup(hass, add_board(hass))
    api.fail["board"] = 500
    for _ in range(3):
        await poll(hass, freezer)
    with patch.object(hass.config_entries, "async_unload_platforms", return_value=False):
        assert not await hass.config_entries.async_unload(entry.entry_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"unreachable_{entry.entry_id}") is not None
    assert hass.data[CONTROLS_OWNER] == entry.entry_id
