"""Config flow against the faked services instead of patched readers: the
station search and the token probe as they go over HTTP, their failures,
reconfiguring a board or a connection that is running, and the token that
is shared by every entry."""
from __future__ import annotations

from unittest.mock import patch

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.swiss_transport.config_flow import SwissTransportConfigFlow
from custom_components.swiss_transport.const import (
    CONF_FROM_ID,
    CONF_FROM_NAME,
    CONF_LIMIT,
    CONF_OJP_TOKEN,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    CONF_TO_ID,
    CONF_TO_NAME,
    DOMAIN,
    OJP_ENDPOINT,
)

from .common import (
    BERN,
    BOARD_ENTITY,
    CONNECTIONS_URL,
    LOCATIONS_URL,
    ROUTE_ENTITY,
    THUN,
    FakeApi,
    add_board,
    add_connection,
    connections,
    setup,
    state_time,
)

ZURICH = {"id": "8503000", "name": "Zürich HB"}


def _defaults(result) -> dict:
    """The pre-filled values of a form."""
    return {str(key): key.default() for key in result["data_schema"].schema if key.default is not vol.UNDEFINED}


async def _start(hass: HomeAssistant, mode: str):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"mode": mode})


async def _reconfigure(hass: HomeAssistant, entry):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )


def _probed_station(api: FakeApi) -> str:
    """The stop the last token probe asked opentransportdata.swiss about."""
    body = api.requests(OJP_ENDPOINT)[-1][2].decode("utf-8")
    return body.split("<siri:StopPointRef>")[1].split("<")[0]


# ---------------------------------------------------------------- new entry


async def test_searched_station_with_a_token_becomes_a_realtime_board(hass: HomeAssistant, api: FakeApi) -> None:
    result = await _start(hass, "station")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "  Bern "})
    assert result["step_id"] == "pick"
    assert api.requests(LOCATIONS_URL)[0][1].query["query"] == "Bern"
    assert _defaults(result) == {CONF_LIMIT: 8, "transportations": [], CONF_OJP_TOKEN: ""}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATION_ID: "8507000", CONF_LIMIT: 4, "transportations": ["train"], CONF_OJP_TOKEN: " made-up-token "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Departures Bern"
    assert result["data"][CONF_OJP_TOKEN] == "made-up-token"
    probe = api.requests(OJP_ENDPOINT)[0]
    assert probe[3]["Authorization"] == "Bearer made-up-token"
    assert "<NumberOfResults>1</NumberOfResults>" in probe[2].decode("utf-8")
    assert _probed_station(api) == "8507000"

    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.state is ConfigEntryState.LOADED
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_departures")
    state = hass.states.get(entity_id)
    assert state.state == state_time(4)
    assert state.attributes["realtime"] is True
    assert state.attributes["limit"] == 4


async def test_unreachable_station_search_is_a_form_error_and_can_be_retried(hass: HomeAssistant, api: FakeApi) -> None:
    api.fail["locations"] = 500
    result = await _start(hass, "station")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "Bern"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "station"
    assert result["errors"] == {"base": "cannot_connect"}

    api.fail.clear()
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "Bern"})
    assert result["step_id"] == "pick"


async def test_unreachable_station_search_is_a_form_error_for_a_connection(hass: HomeAssistant, api: FakeApi) -> None:
    api.fail["locations"] = TimeoutError()
    result = await _start(hass, "connection")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"from_query": "Bern", "to_query": "Thun"})
    assert result["step_id"] == "connection"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_connection_needs_both_stops_to_be_found(hass: HomeAssistant, api: FakeApi) -> None:
    result = await _start(hass, "connection")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"from_query": "Bern", "to_query": "Atlantis"})
    assert result["step_id"] == "connection"
    assert result["errors"] == {"base": "no_stations_found"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"from_query": "Atlantis", "to_query": "Thun"})
    assert result["errors"] == {"base": "no_stations_found"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"from_query": "Bern", "to_query": "Thun"})
    assert result["step_id"] == "connection_pick"
    assert _defaults(result) == {CONF_LIMIT: 6}


async def test_token_that_cannot_be_checked_is_a_form_error(hass: HomeAssistant, api: FakeApi) -> None:
    api.fail["ojp"] = 502
    result = await _start(hass, "station")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "Bern"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATION_ID: "8507000", CONF_LIMIT: 8, "transportations": [], CONF_OJP_TOKEN: "made-up-token"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pick"
    assert result["errors"] == {"base": "cannot_connect"}
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_rejected_token_over_http_is_a_form_error(hass: HomeAssistant, api: FakeApi) -> None:
    api.fail["ojp"] = 403
    result = await _start(hass, "station")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "Bern"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATION_ID: "8507000", CONF_LIMIT: 8, "transportations": [], CONF_OJP_TOKEN: "made-up-token"}
    )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_new_board_is_offered_the_token_already_in_use(hass: HomeAssistant, api: FakeApi) -> None:
    add_connection(hass)
    add_board(hass, entry_id="board0002", station=THUN, options={CONF_OJP_TOKEN: "made-up-token"})
    result = await _start(hass, "station")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "Bern"})
    assert _defaults(result)[CONF_OJP_TOKEN] == "made-up-token"


async def test_pick_without_search_results_starts_over(hass: HomeAssistant) -> None:
    flow = SwissTransportConfigFlow()
    flow.hass = hass
    result = await flow.async_step_pick({CONF_STATION_ID: "8507000"})
    assert (result["type"], result["step_id"]) == (FlowResultType.FORM, "user")
    result = await flow.async_step_connection_pick({CONF_FROM_ID: "from:8507000", CONF_TO_ID: "to:8507100"})
    assert (result["type"], result["step_id"]) == (FlowResultType.FORM, "connection")


# --------------------------------------------------------------- reconfigure


async def test_reconfigured_connection_shows_the_new_route_under_its_entity_id(hass: HomeAssistant, api: FakeApi) -> None:
    api.stations["zürich"] = [ZURICH]
    api.connections = connections(named=False)
    entry = await setup(hass, add_connection(hass, options={CONF_LIMIT: 4}))

    result = await _reconfigure(hass, entry)
    assert result["step_id"] == "connection"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"from_query": "Bern", "to_query": "Zürich"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FROM_ID: "from:8507000", CONF_TO_ID: "to:8503000", CONF_LIMIT: 6}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    assert entry.unique_id == "connection_8507000_8503000"
    assert entry.title == "Bern → Zürich HB"
    assert (entry.data[CONF_FROM_NAME], entry.data[CONF_TO_NAME]) == ("Bern", "Zürich HB")
    assert entry.options == {CONF_LIMIT: 4}
    assert entry.state is ConfigEntryState.LOADED
    assert api.requests(CONNECTIONS_URL)[-1][1].query["to"] == "8503000"
    # The unique id belongs to the entry, so the registry hands the entity
    # its former id back; it now shows the new route.
    registered = er.async_get(hass).async_get(ROUTE_ENTITY)
    assert registered.unique_id == "route0001_connections"
    attrs = hass.states.get(ROUTE_ENTITY).attributes
    assert (attrs["to_id"], attrs["to_name"]) == ("8503000", "Zürich HB")
    assert dr.async_get(hass).async_get(registered.device_id).name == "Bern → Zürich HB"


async def test_reconfigured_board_keeps_its_entity_when_the_station_stays(hass: HomeAssistant, api: FakeApi) -> None:
    entry = await setup(hass, add_board(hass))
    registry = er.async_get(hass)
    before = registry.async_get(BOARD_ENTITY).id

    result = await _reconfigure(hass, entry)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "Bern"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATION_ID: "8507000", CONF_LIMIT: 12, "transportations": ["train"], CONF_OJP_TOKEN: ""}
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    assert entry.unique_id == "station_8507000"
    assert entry.data[CONF_LIMIT] == 12
    assert entry.data["transportations"] == ["train"]
    assert registry.async_get(BOARD_ENTITY).id == before
    assert hass.states.get(BOARD_ENTITY).attributes["limit"] == 12


async def test_board_cannot_be_moved_onto_a_station_that_has_one(hass: HomeAssistant, api: FakeApi) -> None:
    entry = add_board(hass)
    add_board(hass, entry_id="board0002", station=THUN)
    result = await _reconfigure(hass, entry)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "Thun"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATION_ID: "8507100", CONF_LIMIT: 8, "transportations": [], CONF_OJP_TOKEN: ""}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_STATION_NAME] == "Bern"


async def test_reconfigure_reloads_once_when_the_listener_already_reloads(hass: HomeAssistant, api: FakeApi) -> None:
    entry = add_board(hass)
    result = await _reconfigure(hass, entry)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "Thun"})
    with (
        patch("custom_components.swiss_transport.config_flow._LISTENER_RELOADS", True),
        patch.object(hass.config_entries, "async_schedule_reload") as reload,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_STATION_ID: "8507100", CONF_LIMIT: 8, "transportations": [], CONF_OJP_TOKEN: ""}
        )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_STATION_ID] == "8507100"
    reload.assert_not_called()


# ------------------------------------------------- the token, shared by all


async def test_reauth_on_a_connection_probes_with_the_stop_of_a_board(hass: HomeAssistant, api: FakeApi) -> None:
    route = add_connection(hass, options={CONF_OJP_TOKEN: "old-token"})
    add_board(hass, entry_id="board0002", station=THUN)
    result = await route.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_OJP_TOKEN: "new-token"})
    assert result["reason"] == "reauth_successful"
    assert _probed_station(api) == "8507100"


async def test_reauth_without_any_board_probes_with_bern(hass: HomeAssistant, api: FakeApi) -> None:
    route = add_connection(hass, options={CONF_OJP_TOKEN: "old-token"})
    result = await route.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_OJP_TOKEN: "new-token"})
    assert result["reason"] == "reauth_successful"
    assert _probed_station(api) == BERN["id"]
    assert route.options[CONF_OJP_TOKEN] == "new-token"


async def test_new_token_reaches_every_entry_and_leaves_the_entry_data(hass: HomeAssistant, api: FakeApi) -> None:
    asked = add_board(hass, options={CONF_OJP_TOKEN: "old-token"})
    legacy = add_board(hass, entry_id="board0002", station=THUN, **{CONF_OJP_TOKEN: "old-token"})
    current = add_board(hass, entry_id="board0003", station=ZURICH, options={CONF_OJP_TOKEN: "new-token", CONF_LIMIT: 5})
    route = add_connection(hass)

    result = await asked.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_OJP_TOKEN: "new-token"})
    assert result["reason"] == "reauth_successful"
    assert asked.options[CONF_OJP_TOKEN] == "new-token"
    assert legacy.options[CONF_OJP_TOKEN] == "new-token"
    assert CONF_OJP_TOKEN not in legacy.data
    assert legacy.data[CONF_STATION_ID] == "8507100"
    assert current.options == {CONF_OJP_TOKEN: "new-token", CONF_LIMIT: 5}
    assert route.options[CONF_OJP_TOKEN] == "new-token"


async def test_removed_token_is_gone_from_options_and_entry_data_alike(hass: HomeAssistant, api: FakeApi) -> None:
    asked = add_board(hass, options={CONF_OJP_TOKEN: "old-token"}, **{CONF_OJP_TOKEN: "old-token"})
    legacy = add_board(hass, entry_id="board0002", station=THUN, **{CONF_OJP_TOKEN: "old-token"})
    route = add_connection(hass, options={CONF_OJP_TOKEN: "old-token", CONF_LIMIT: 4})

    result = await asked.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_OJP_TOKEN: ""})
    assert result["reason"] == "reauth_successful"
    assert api.requests(OJP_ENDPOINT) == []
    for entry in (asked, legacy, route):
        assert CONF_OJP_TOKEN not in entry.options
        assert CONF_OJP_TOKEN not in entry.data
    assert route.options == {CONF_LIMIT: 4}
