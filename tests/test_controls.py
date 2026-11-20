"""The dashboard-wide time and mode controls: created once however many
entries there are, set through their services, restored after a restart and
handed over when the entry that owns them is unloaded."""
from __future__ import annotations

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.swiss_transport.const import (
    CONTROL_MODE_UNIQUE,
    CONTROL_TIME_UNIQUE,
    CONTROLS_OWNER,
    DOMAIN,
    MODE_ENTITY_ID,
    TIME_ENTITY_ID,
    VERSION,
)

from .common import FakeApi, add_board, add_connection, setup, state_time


async def test_controls_exist_once_for_several_entries(hass: HomeAssistant, api: FakeApi) -> None:
    first = await setup(hass, add_board(hass))
    await setup(hass, add_connection(hass))
    registry = er.async_get(hass)
    times = [entity for entity in registry.entities.values() if entity.domain == "datetime"]
    modes = [entity for entity in registry.entities.values() if entity.domain == "select"]
    assert [(entity.entity_id, entity.unique_id, entity.config_entry_id) for entity in times] == [
        (TIME_ENTITY_ID, CONTROL_TIME_UNIQUE, first.entry_id)
    ]
    assert [(entity.entity_id, entity.unique_id, entity.config_entry_id) for entity in modes] == [
        (MODE_ENTITY_ID, CONTROL_MODE_UNIQUE, first.entry_id)
    ]
    assert hass.data[CONTROLS_OWNER] == first.entry_id


async def test_controls_share_one_device(hass: HomeAssistant, api: FakeApi) -> None:
    await setup(hass, add_board(hass))
    registry = er.async_get(hass)
    device_ids = {registry.async_get(TIME_ENTITY_ID).device_id, registry.async_get(MODE_ENTITY_ID).device_id}
    assert len(device_ids) == 1
    device = dr.async_get(hass).async_get(device_ids.pop())
    assert device.identifiers == {(DOMAIN, "controls")}
    assert device.name == "Departures dashboard controls"
    assert device.model == "Dashboard controls"
    assert device.sw_version == VERSION


async def test_controls_start_live_and_at_the_present_moment(hass: HomeAssistant, api: FakeApi) -> None:
    await setup(hass, add_board(hass))
    assert hass.states.get(TIME_ENTITY_ID).state == state_time(0)
    assert hass.states.get(TIME_ENTITY_ID).attributes["friendly_name"] == "Departures dashboard controls Timetable moment"
    mode = hass.states.get(MODE_ENTITY_ID)
    assert mode.state == "live"
    assert mode.attributes["options"] == ["live", "depart", "arrive"]
    assert mode.attributes["friendly_name"] == "Departures dashboard controls Timetable mode"


async def test_time_and_mode_are_set_through_their_services(hass: HomeAssistant, api: FakeApi) -> None:
    await setup(hass, add_board(hass))
    await hass.services.async_call(
        "datetime", "set_value", {"entity_id": TIME_ENTITY_ID, "datetime": "2026-12-24T17:30:00+00:00"}, blocking=True
    )
    await hass.services.async_call("select", "select_option", {"entity_id": MODE_ENTITY_ID, "option": "arrive"}, blocking=True)
    assert hass.states.get(TIME_ENTITY_ID).state == "2026-12-24T17:30:00+00:00"
    assert hass.states.get(MODE_ENTITY_ID).state == "arrive"


async def test_unknown_mode_is_refused(hass: HomeAssistant, api: FakeApi) -> None:
    await setup(hass, add_board(hass))
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "select", "select_option", {"entity_id": MODE_ENTITY_ID, "option": "sideways"}, blocking=True
        )
    assert hass.states.get(MODE_ENTITY_ID).state == "live"


async def test_time_and_mode_come_back_after_a_restart(hass: HomeAssistant, api: FakeApi) -> None:
    mock_restore_cache(hass, [State(TIME_ENTITY_ID, "2026-12-24T17:30:00+00:00"), State(MODE_ENTITY_ID, "depart")])
    await setup(hass, add_board(hass))
    assert hass.states.get(TIME_ENTITY_ID).state == "2026-12-24T17:30:00+00:00"
    assert hass.states.get(MODE_ENTITY_ID).state == "depart"


@pytest.mark.parametrize("stored_time", ["unknown", "unavailable", "half past five"])
async def test_unusable_stored_values_fall_back_to_now_and_live(hass: HomeAssistant, api: FakeApi, stored_time: str) -> None:
    mock_restore_cache(hass, [State(TIME_ENTITY_ID, stored_time), State(MODE_ENTITY_ID, "sideways")])
    await setup(hass, add_board(hass))
    assert hass.states.get(TIME_ENTITY_ID).state == state_time(0)
    assert hass.states.get(MODE_ENTITY_ID).state == "live"


async def test_another_entry_takes_the_controls_over_after_the_owner_is_unloaded(hass: HomeAssistant, api: FakeApi) -> None:
    owner = await setup(hass, add_board(hass))
    other = await setup(hass, add_connection(hass))
    await hass.services.async_call("select", "select_option", {"entity_id": MODE_ENTITY_ID, "option": "depart"}, blocking=True)

    assert await hass.config_entries.async_unload(owner.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(MODE_ENTITY_ID).state == STATE_UNAVAILABLE
    assert CONTROLS_OWNER not in hass.data

    assert await hass.config_entries.async_reload(other.entry_id)
    await hass.async_block_till_done()
    assert hass.data[CONTROLS_OWNER] == other.entry_id
    assert hass.states.get(MODE_ENTITY_ID).state == "depart"
    assert hass.states.get(TIME_ENTITY_ID).state == state_time(0)
    assert er.async_get(hass).async_get(MODE_ENTITY_ID).config_entry_id == other.entry_id
