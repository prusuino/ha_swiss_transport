"""The departure-board and connection sensors after a real setup: state,
attributes, attribution, the registry entries and the devices."""
from __future__ import annotations

from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.swiss_transport.const import CONF_LIMIT, CONF_LINE_LABEL, DOMAIN, VERSION

from .common import (
    BERN,
    BOARD_ENTITY,
    BOARD_URL,
    CONNECTIONS_URL,
    ROUTE_ENTITY,
    THUN,
    FakeApi,
    add_board,
    add_connection,
    board,
    connection,
    connections,
    departure,
    setup,
    state_time,
    ts,
)


async def test_board_sensor_shows_the_next_departure_and_the_whole_board(hass: HomeAssistant, api: FakeApi) -> None:
    api.board = board([departure(12, "IR", "16"), departure(4, "S", "9", "Thun", delay=2, platform="3", new_platform="5")])
    await setup(hass, add_board(hass))
    state = hass.states.get(BOARD_ENTITY)
    assert state.state == state_time(4)
    attrs = state.attributes
    assert attrs["device_class"] == "timestamp"
    assert attrs["friendly_name"] == "Bern Departures"
    assert attrs["station_id"] == "8507000"
    assert attrs["station_name"] == "Bern"
    assert attrs["address"] == "Bahnhofplatz, 3011 Bern"
    assert (attrs["latitude"], attrs["longitude"]) == (46.949, 7.439)
    assert attrs["departure_count"] == 2
    assert attrs["limit"] == 8
    assert attrs["line_label"] == "category"
    assert attrs["realtime"] is False
    assert attrs["alerts"] == []
    assert attrs["attribution"] == "Data: transport.opendata.ch (opentransportdata.swiss). Address: © OpenStreetMap contributors"
    first, second = attrs["departures"]
    assert first == {
        "line": "S",
        "category": "S",
        "number": "9",
        "to": "Thun",
        "operator": "SBB",
        "departure": "2026-11-09T07:04:00+0100",
        "departure_ts": ts(4),
        "delay": 2,
        "platform": "3",
        "platform_changed": True,
        "cancelled": False,
    }
    assert second["line"] == "IR"
    assert second["platform_changed"] is False


async def test_board_is_requested_as_the_options_say(hass: HomeAssistant, api: FakeApi) -> None:
    options = {CONF_LIMIT: 3, "transportations": ["train", "bus"], CONF_LINE_LABEL: "full"}
    await setup(hass, add_board(hass, options=options))
    query = api.requests(BOARD_URL)[0][1].query
    assert query["id"] == "8507000"
    assert query["limit"] == "3"
    assert query.getall("transportations") == ["train", "bus"]
    attrs = hass.states.get(BOARD_ENTITY).attributes
    assert attrs["limit"] == 3
    assert attrs["line_label"] == "full"
    assert [dep["line"] for dep in attrs["departures"]] == ["S9", "IC8"]


async def test_board_without_departures_is_unknown(hass: HomeAssistant, api: FakeApi) -> None:
    api.board = board([])
    await setup(hass, add_board(hass))
    state = hass.states.get(BOARD_ENTITY)
    assert state.state == STATE_UNKNOWN
    assert state.attributes["departure_count"] == 0
    assert state.attributes["departures"] == []


async def test_board_sensor_and_device_are_registered_under_the_station(hass: HomeAssistant, api: FakeApi) -> None:
    entry = await setup(hass, add_board(hass))
    registered = er.async_get(hass).async_get(BOARD_ENTITY)
    assert registered.unique_id == "board0001_departures"
    assert registered.config_entry_id == entry.entry_id
    device = dr.async_get(hass).async_get(registered.device_id)
    assert device.identifiers == {(DOMAIN, entry.entry_id)}
    assert device.name == "Bern"
    assert device.model == "Departure board"
    assert device.manufacturer == "transport.opendata.ch"
    assert device.sw_version == VERSION


async def test_entry_without_a_station_name_is_named_by_its_title(hass: HomeAssistant, api: FakeApi) -> None:
    entry = add_board(hass, station_name=None)
    hass.config_entries.async_update_entry(entry, title="Luzern")
    await setup(hass, entry)
    registered = er.async_get(hass).async_get("sensor.swiss_transport_luzern_0001")
    assert registered.unique_id == "board0001_departures"
    assert dr.async_get(hass).async_get(registered.device_id).name == "Luzern"


async def test_two_stops_with_the_same_name_get_different_entity_ids(hass: HomeAssistant, api: FakeApi) -> None:
    await setup(hass, add_board(hass))
    await setup(hass, add_board(hass, entry_id="board0002", station={"id": "8590125", "name": "Bern"}))
    assert hass.states.get("sensor.swiss_transport_bern_0001") is not None
    assert hass.states.get("sensor.swiss_transport_bern_0002") is not None


async def test_names_follow_the_language_of_home_assistant(hass: HomeAssistant, api: FakeApi) -> None:
    hass.config.language = "de-CH"
    await setup(hass, add_board(hass))
    await setup(hass, add_connection(hass))
    assert hass.states.get(BOARD_ENTITY).attributes["friendly_name"] == "Bern Abfahrten"
    assert hass.states.get(ROUTE_ENTITY).attributes["friendly_name"] == "Bern → Thun Verbindungen"


async def test_connection_sensor_shows_the_next_connection_and_the_list(hass: HomeAssistant, api: FakeApi) -> None:
    api.connections = connections([connection(36, delay=None), connection(6, delay=3)])
    await setup(hass, add_connection(hass, options={CONF_LIMIT: 4, CONF_LINE_LABEL: "full"}))
    query = api.requests(CONNECTIONS_URL)[0][1].query
    assert (query["from"], query["to"], query["limit"]) == (BERN["id"], THUN["id"], "4")

    state = hass.states.get(ROUTE_ENTITY)
    assert state.state == state_time(6)
    attrs = state.attributes
    assert attrs["device_class"] == "timestamp"
    assert attrs["friendly_name"] == "Bern → Thun Connections"
    assert attrs["attribution"] == "Data: transport.opendata.ch (opentransportdata.swiss)"
    assert (attrs["from_name"], attrs["to_name"]) == ("Bern", "Thun")
    assert (attrs["from_id"], attrs["to_id"]) == (BERN["id"], THUN["id"])
    assert attrs["connection_count"] == 2
    assert attrs["limit"] == 4
    assert attrs["line_label"] == "full"
    first, second = attrs["connections"]
    assert first["departure_ts"] == ts(6)
    assert first["arrival_ts"] == ts(26)
    assert first["duration_min"] == 20
    assert first["delay"] == 3
    assert first["dep_platform"] == "4"
    assert first["arr_platform"] == "2"
    assert first["transfers"] == 0
    assert first["changes"] == []
    assert first["legs"] == [
        {
            "line": "IC6",
            "category": "IC",
            "number": "6",
            "operator": "SBB",
            "to": "Brig",
            "from_name": "Bern",
            "from_platform": "4",
            "to_name": "Thun",
            "to_platform": "2",
        }
    ]
    assert second["delay"] is None


async def test_connection_without_results_is_unknown_and_keeps_its_names(hass: HomeAssistant, api: FakeApi) -> None:
    api.connections = connections([], named=False)
    await setup(hass, add_connection(hass))
    state = hass.states.get(ROUTE_ENTITY)
    assert state.state == STATE_UNKNOWN
    assert state.attributes["connection_count"] == 0
    assert (state.attributes["from_name"], state.attributes["to_name"]) == ("Bern", "Thun")
    assert state.attributes["limit"] == 6


async def test_connection_sensor_and_device_are_registered_under_the_route(hass: HomeAssistant, api: FakeApi) -> None:
    entry = await setup(hass, add_connection(hass))
    registered = er.async_get(hass).async_get(ROUTE_ENTITY)
    assert registered.unique_id == "route0001_connections"
    device = dr.async_get(hass).async_get(registered.device_id)
    assert device.identifiers == {(DOMAIN, entry.entry_id)}
    assert device.name == "Bern → Thun"
    assert device.model == "Connection"
    assert device.sw_version == VERSION
