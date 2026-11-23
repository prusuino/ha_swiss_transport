"""The two triggers across a gap without a value, with real automations on a
registered board whose state is set by hand: a delay or a disruption that
is there when the board comes back from an outage is reported once."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.swiss_transport.const import DOMAIN

TIME = "2026-11-23T18:04:00+00:00"


def _board(hass: HomeAssistant) -> str:
    return er.async_get(hass).async_get_or_create("sensor", DOMAIN, "entry_board", suggested_object_id="board", original_device_class="timestamp").entity_id


async def _show(hass: HomeAssistant, board: str, delay: int | None = 0, alerts: list[str] | None = None, state: str = TIME) -> None:
    attributes: dict = {"device_class": "timestamp"}
    if state == TIME:
        attributes["departures"] = [{"delay": delay}] if delay is not None else []
        attributes["alerts"] = alerts or []
    hass.states.async_set(board, state, attributes)
    await hass.async_block_till_done()


async def _automation(hass: HomeAssistant, name: str, board: str, **options) -> list:
    calls = async_mock_service(hass, "test", name)
    assert await async_setup_component(hass, "automation", {"automation": {
        "alias": name, "trigger": {"trigger": f"swiss_transport.{name}", "target": {"entity_id": board}, "options": options},
        "action": {"action": f"test.{name}"},
    }})
    await hass.async_block_till_done()
    assert hass.states.get(f"automation.{name}") is not None, "the automation was rejected"
    return calls


async def test_a_delay_that_is_there_after_an_outage_is_reported_once(hass: HomeAssistant, enable_custom_integrations) -> None:
    board = _board(hass)
    await _show(hass, board, delay=0)
    calls = await _automation(hass, "departure_delayed", board, minimum_delay=5)
    await _show(hass, board, state="unavailable")
    await _show(hass, board, delay=8)  # on time before the outage, late after it
    assert len(calls) == 1
    await _show(hass, board, state="unavailable")
    await _show(hass, board, delay=9)  # still late: quiet
    assert len(calls) == 1
    await _show(hass, board, delay=0)
    await _show(hass, board, state="unknown")
    await _show(hass, board, delay=3)  # below the minimum
    assert len(calls) == 1
    await _show(hass, board, delay=6)
    assert len(calls) == 2


async def test_a_delay_with_nothing_known_from_before(hass: HomeAssistant, enable_custom_integrations) -> None:
    board = _board(hass)
    await _show(hass, board, state="unavailable")
    calls = await _automation(hass, "departure_delayed", board)
    await _show(hass, board, delay=None)  # an empty board
    assert len(calls) == 0
    await _show(hass, board, state="unavailable")
    await _show(hass, board, delay=7)
    assert len(calls) == 1


async def test_a_disruption_after_an_outage(hass: HomeAssistant, enable_custom_integrations) -> None:
    board = _board(hass)
    await _show(hass, board, state="unavailable")
    calls = await _automation(hass, "disruption_reported", board)
    await _show(hass, board, alerts=["Streckenunterbruch"])  # nothing known from before: reported
    assert len(calls) == 1
    await _show(hass, board, state="unavailable")
    await _show(hass, board, alerts=["Streckenunterbruch"])  # the same disruption
    assert len(calls) == 1
    await _show(hass, board, alerts=[])
    await _show(hass, board, state="unavailable")
    await _show(hass, board, alerts=["Fahrleitungsstörung"])
    assert len(calls) == 2
    await _show(hass, board, alerts=["Fahrleitungsstörung", "Ersatzbus"])  # still disrupted
    assert len(calls) == 2
