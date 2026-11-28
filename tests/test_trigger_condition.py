"""The triggers and conditions for the automation editor, tried with real
automations on a board and a connection that are refreshed with new answers:
when they fire, when they stay quiet, and that entities of other
integrations in the target are ignored."""
from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.automation import filter_by_domain_specs
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.swiss_transport import condition, trigger

from .common import (
    BOARD_ENTITY,
    ROUTE_ENTITY,
    FakeApi,
    add_board,
    add_connection,
    board,
    connection,
    connections,
    departure,
    ojp_situation,
    ojp_xml,
    poll,
    setup,
)

TOKEN = {"ojp_token": "made-up-token"}
FOREIGN_ENTITY = "sensor.backup_last_run"


async def _automation(hass: HomeAssistant, *, trigger: dict | None = None, condition: dict | None = None) -> list:
    """An automation with the given trigger (or a test event) and condition;
    returns the list its action calls are collected in."""
    calls = async_mock_service(hass, "test", "automation")
    config = {
        "alias": "Tell me",
        "trigger": trigger or {"trigger": "event", "event_type": "check_now"},
        "action": {"action": "test.automation"},
    }
    if condition:
        config["condition"] = condition
    assert await async_setup_component(hass, "automation", {"automation": config})
    await hass.async_block_till_done()
    assert hass.states.get("automation.tell_me") is not None, "the automation was rejected"
    return calls


async def _check(hass: HomeAssistant, calls: list) -> bool:
    """Run the event-triggered automation once; whether its condition let it through."""
    before = len(calls)
    hass.bus.async_fire("check_now")
    await hass.async_block_till_done()
    return len(calls) > before


def _delayed(entity_id: str, **options) -> dict:
    return {"trigger": "swiss_transport.departure_delayed", "target": {"entity_id": entity_id}, "options": options}


def _is_delayed(entity_id: str, **options) -> dict:
    return {"condition": "swiss_transport.is_departure_delayed", "target": {"entity_id": entity_id}, "options": options}


def _set_foreign(hass: HomeAssistant, delay: int, alerts: list[str]) -> None:
    hass.states.async_set(
        FOREIGN_ENTITY,
        "2026-11-09T06:04:00+00:00",
        {"device_class": "timestamp", "departures": [{"delay": delay}], "alerts": alerts},
    )


def _foreign_board(hass: HomeAssistant) -> None:
    """A timestamp sensor of another integration that looks like a delayed,
    disrupted departure board."""
    registered = er.async_get(hass).async_get_or_create(
        "sensor", "another_integration", "backup_last_run", suggested_object_id="backup_last_run",
        original_device_class="timestamp",
    )
    assert registered.entity_id == FOREIGN_ENTITY
    _set_foreign(hass, 0, [])
    # Home Assistant's own filter (sensor with device class timestamp) lets it through.
    assert filter_by_domain_specs(hass, trigger.BOARD_DOMAIN_SPECS, {FOREIGN_ENTITY}) == {FOREIGN_ENTITY}


async def test_all_triggers_and_both_conditions_are_offered(hass: HomeAssistant) -> None:
    assert set(await trigger.async_get_triggers(hass)) == {
        "departure_delayed", "departure_cancelled", "platform_changed", "disruption_reported"
    }
    assert set(await condition.async_get_conditions(hass)) == {"is_departure_delayed", "has_disruption"}


# ----------------------------------------------------------------- triggers


async def test_delay_trigger_fires_when_the_minimum_is_reached_and_not_while_it_lasts(
    hass: HomeAssistant, api: FakeApi, freezer
) -> None:
    await setup(hass, add_board(hass))
    calls = await _automation(hass, trigger=_delayed(BOARD_ENTITY, minimum_delay=5))

    api.board = board([departure(4, delay=3), departure(12, delay=30)])
    await poll(hass, freezer)
    assert len(calls) == 0  # below the minimum; only the next departure counts

    api.board = board([departure(4, delay=5), departure(12)])
    await poll(hass, freezer)
    assert len(calls) == 1

    api.board = board([departure(4, delay=9), departure(12)])
    await poll(hass, freezer)
    assert len(calls) == 1  # still delayed: quiet

    api.board = board([departure(4, delay=None), departure(12)])
    await poll(hass, freezer)
    api.board = board([departure(4, delay=6), departure(12)])
    await poll(hass, freezer)
    assert len(calls) == 2


async def test_delay_trigger_uses_five_minutes_unless_told_otherwise(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    await setup(hass, add_board(hass))
    calls = await _automation(hass, trigger=_delayed(BOARD_ENTITY))
    api.board = board([departure(4, delay=4)])
    await poll(hass, freezer)
    assert len(calls) == 0
    api.board = board([departure(4, delay=5)])
    await poll(hass, freezer)
    assert len(calls) == 1


async def test_delay_trigger_watches_the_next_connection_of_a_route(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    await setup(hass, add_connection(hass))
    calls = await _automation(hass, trigger=_delayed(ROUTE_ENTITY, minimum_delay=2))
    api.connections = connections([connection(6, delay=2), connection(36)])
    await poll(hass, freezer, 301)
    assert len(calls) == 1


async def test_delay_trigger_refuses_a_minimum_outside_the_range(hass: HomeAssistant, api: FakeApi) -> None:
    await setup(hass, add_board(hass))
    async_mock_service(hass, "test", "automation")
    config = {"alias": "Tell me", "trigger": _delayed(BOARD_ENTITY, minimum_delay=0), "action": {"action": "test.automation"}}
    assert await async_setup_component(hass, "automation", {"automation": config})
    await hass.async_block_till_done()
    assert hass.states.get("automation.tell_me").state == "unavailable"


async def test_disruption_trigger_fires_when_a_message_appears(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    await setup(hass, add_board(hass, options=TOKEN))
    calls = await _automation(
        hass, trigger={"trigger": "swiss_transport.disruption_reported", "target": {"entity_id": BOARD_ENTITY}}
    )
    await poll(hass, freezer)
    assert len(calls) == 0

    api.ojp = ojp_xml(situations=[ojp_situation("Bern: track works until Friday")])
    await poll(hass, freezer)
    assert len(calls) == 1

    api.ojp = ojp_xml(situations=[ojp_situation("Bern: track works until Friday"), ojp_situation("Lift out of order")])
    await poll(hass, freezer)
    assert len(calls) == 1  # a second message while one is open: quiet

    api.ojp = ojp_xml()
    await poll(hass, freezer)
    api.ojp = ojp_xml(situations=[ojp_situation("Lift out of order")])
    await poll(hass, freezer)
    assert len(calls) == 2


async def test_triggers_ignore_entities_of_other_integrations(hass: HomeAssistant, api: FakeApi) -> None:
    await setup(hass, add_board(hass))
    _foreign_board(hass)
    delayed = await _automation(hass, trigger=_delayed([BOARD_ENTITY, FOREIGN_ENTITY], minimum_delay=5))
    _set_foreign(hass, 12, ["Backup storage is full"])
    await hass.async_block_till_done()
    assert len(delayed) == 0


async def test_disruption_trigger_ignores_entities_of_other_integrations(hass: HomeAssistant, api: FakeApi) -> None:
    await setup(hass, add_board(hass))
    _foreign_board(hass)
    calls = await _automation(
        hass,
        trigger={"trigger": "swiss_transport.disruption_reported", "target": {"entity_id": [BOARD_ENTITY, FOREIGN_ENTITY]}},
    )
    _set_foreign(hass, 12, ["Backup storage is full"])
    await hass.async_block_till_done()
    assert len(calls) == 0


# --------------------------------------------------------------- conditions


async def test_delay_condition_follows_the_next_departure(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    api.board = board([departure(4, delay=4), departure(12, delay=30)])
    await setup(hass, add_board(hass))
    calls = await _automation(hass, condition=_is_delayed(BOARD_ENTITY, minimum_delay=5))
    assert not await _check(hass, calls)

    api.board = board([departure(4, delay=5), departure(12)])
    await poll(hass, freezer)
    assert await _check(hass, calls)

    api.board = board([departure(4, delay=None), departure(12)])
    await poll(hass, freezer)
    assert not await _check(hass, calls)

    api.board = board([])
    await poll(hass, freezer)
    assert not await _check(hass, calls)


async def test_delay_condition_uses_five_minutes_unless_told_otherwise(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    api.connections = connections([connection(6, delay=4)])
    await setup(hass, add_connection(hass))
    calls = await _automation(hass, condition=_is_delayed(ROUTE_ENTITY))
    assert not await _check(hass, calls)
    api.connections = connections([connection(6, delay=5)])
    await poll(hass, freezer, 301)
    assert await _check(hass, calls)


async def test_disruption_condition_follows_the_messages_of_the_stop(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    await setup(hass, add_board(hass, options=TOKEN))
    calls = await _automation(
        hass, condition={"condition": "swiss_transport.has_disruption", "target": {"entity_id": BOARD_ENTITY}}
    )
    assert not await _check(hass, calls)
    api.ojp = ojp_xml(situations=[ojp_situation("Bern: track works until Friday")])
    await poll(hass, freezer)
    assert await _check(hass, calls)


async def test_conditions_ignore_entities_of_other_integrations(hass: HomeAssistant, api: FakeApi) -> None:
    await setup(hass, add_board(hass))
    _foreign_board(hass)
    _set_foreign(hass, 12, ["Backup storage is full"])
    delayed = await _automation(hass, condition=_is_delayed([BOARD_ENTITY, FOREIGN_ENTITY], minimum_delay=5))
    assert not await _check(hass, delayed)


async def test_disruption_condition_ignores_entities_of_other_integrations(hass: HomeAssistant, api: FakeApi) -> None:
    await setup(hass, add_board(hass))
    _foreign_board(hass)
    _set_foreign(hass, 12, ["Backup storage is full"])
    calls = await _automation(
        hass,
        condition={"condition": "swiss_transport.has_disruption", "target": {"entity_id": [BOARD_ENTITY, FOREIGN_ENTITY]}},
    )
    assert not await _check(hass, calls)


# ------------------------------------------------------ older Home Assistant


@pytest.mark.parametrize(("module", "offered", "known"), [(trigger, "TRIGGERS", 4), (condition, "CONDITIONS", 2)])
def test_an_older_home_assistant_is_offered_nothing(module, offered: str, known: int) -> None:
    count = len(getattr(module, offered))
    try:
        with patch.dict(sys.modules, {"homeassistant.helpers.automation": None}):
            importlib.reload(module)
            assert getattr(module, offered) == {}
    finally:
        importlib.reload(module)
    assert len(getattr(module, offered)) == count == known
