"""Config flow tests: departure board and connection setup, duplicate
detection, a rejected real-time token and the reconfigure flow. The
transport.opendata.ch searches are faked."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.swiss_transport.const import (
    CONF_ENTRY_TYPE,
    CONF_FROM_ID,
    CONF_LIMIT,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    CONF_TO_ID,
    DOMAIN,
    ENTRY_TYPE_CONNECTION,
    ENTRY_TYPE_STATION,
)
from custom_components.swiss_transport.coordinator import OjpAuthError

STATIONS = {
    "olten": [{"id": "8500218", "name": "Olten"}, {"id": "8500219", "name": "Olten Hammer"}],
    "bern": [{"id": "8507000", "name": "Bern"}],
    "chur": [{"id": "8509000", "name": "Chur"}],
}


async def _search(hass, query: str):
    return STATIONS.get(query.lower(), [])


@pytest.fixture
def fake_search():
    with patch("custom_components.swiss_transport.config_flow.async_search_stations", side_effect=_search):
        yield


async def test_departure_board_setup(hass: HomeAssistant, enable_custom_integrations, fake_search) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"mode": "station"})
    assert result["step_id"] == "station"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "Olten"})
    assert result["step_id"] == "pick"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATION_ID: "8500218", CONF_LIMIT: 5, "transportations": ["train"], "ojp_token": ""}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ENTRY_TYPE] == ENTRY_TYPE_STATION
    assert result["data"][CONF_STATION_ID] == "8500218"
    assert result["data"][CONF_STATION_NAME] == "Olten"
    assert result["data"][CONF_LIMIT] == 5
    assert "ojp_token" not in result["data"]
    assert result["result"].unique_id == "station_8500218"


async def test_no_station_found_shows_error(hass: HomeAssistant, enable_custom_integrations, fake_search) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"mode": "station"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "Atlantis"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "station"
    assert result["errors"] == {"base": "no_stations_found"}


async def test_rejected_realtime_token_is_a_form_error(hass: HomeAssistant, enable_custom_integrations, fake_search) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"mode": "station"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "Olten"})
    with patch("custom_components.swiss_transport.config_flow.async_validate_ojp_token", side_effect=OjpAuthError(401)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_STATION_ID: "8500218", CONF_LIMIT: 5, "transportations": [], "ojp_token": "bad-token"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_same_station_twice_is_refused(hass: HomeAssistant, enable_custom_integrations, fake_search) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="station_8500218", title="Olten", data={CONF_ENTRY_TYPE: ENTRY_TYPE_STATION, CONF_STATION_ID: "8500218"}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"mode": "station"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "Olten"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATION_ID: "8500218", CONF_LIMIT: 5, "transportations": [], "ojp_token": ""}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_connection_setup(hass: HomeAssistant, enable_custom_integrations, fake_search) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"mode": "connection"})
    assert result["step_id"] == "connection"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"from_query": "Bern", "to_query": "Chur"})
    assert result["step_id"] == "connection_pick"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FROM_ID: "from:8507000", CONF_TO_ID: "to:8509000", CONF_LIMIT: 3}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ENTRY_TYPE] == ENTRY_TYPE_CONNECTION
    assert result["data"][CONF_FROM_ID] == "8507000"
    assert result["data"][CONF_TO_ID] == "8509000"
    assert result["result"].unique_id == "connection_8507000_8509000"


async def test_reconfigure_moves_the_board_to_another_stop(hass: HomeAssistant, enable_custom_integrations, fake_search) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="station_8500218", title="Olten",
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_STATION, CONF_STATION_ID: "8500218", CONF_STATION_NAME: "Olten", CONF_LIMIT: 5, "transportations": []},
        options={CONF_LIMIT: 8},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    assert result["step_id"] == "station"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "Bern"})
    assert result["step_id"] == "pick"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATION_ID: "8507000", CONF_LIMIT: 5, "transportations": [], "ojp_token": ""}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert entry.unique_id == "station_8507000"
    assert entry.data[CONF_STATION_NAME] == "Bern"
    assert entry.options[CONF_LIMIT] == 8  # the options stay
