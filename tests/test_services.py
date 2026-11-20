"""The actions with response data, `get_departures` and `get_connections`:
stops by name or id, the returned records, and the errors for an unknown
stop, an unreachable API and an exhausted quota."""
from __future__ import annotations

from datetime import datetime

import aiohttp
import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component

from custom_components.swiss_transport.const import DOMAIN
from custom_components.swiss_transport.services import async_register_services

from .common import (
    BERN,
    BOARD_URL,
    CONNECTIONS_URL,
    LOCATIONS_URL,
    THUN,
    FakeApi,
    board,
    connection,
    connections,
    departure,
    ts,
)


@pytest.fixture
async def actions(hass: HomeAssistant, api: FakeApi) -> FakeApi:
    """The integration loaded without any entry: the actions do not need one."""
    assert await async_setup_component(hass, DOMAIN, {})
    return api


async def _call(hass: HomeAssistant, action: str, **data):
    return await hass.services.async_call(DOMAIN, action, data, blocking=True, return_response=True)


def _unix(text: str) -> int:
    return int(datetime.fromisoformat(text).timestamp())


async def test_departures_for_a_stop_given_by_name(hass: HomeAssistant, actions: FakeApi) -> None:
    actions.stations["bern"] = [{"id": None, "name": "Bern (no id)"}, {"id": "8500000", "name": ""}, BERN, THUN]
    actions.board = board([departure(12), departure(4, "S", "9", "Thun", delay=2, platform="3", new_platform="5")])
    response = await _call(hass, "get_departures", station=" Bern ")

    assert dict(actions.requests(LOCATIONS_URL)[0][1].query) == {"query": "Bern", "type": "station"}
    query = actions.requests(BOARD_URL)[0][1].query
    assert (query["id"], query["limit"]) == ("8507000", "8")
    assert "transportations" not in query

    assert response["station_id"] == "8507000"
    assert response["station_name"] == "Bern"
    first, second = response["departures"]
    assert _unix(first.pop("departure")) == ts(4)
    assert first == {
        "line": "S",
        "category": "S",
        "number": "9",
        "to": "Thun",
        "operator": "SBB",
        "in_minutes": 4,
        "delay": 2,
        "platform": "3",
        "platform_changed": True,
    }
    assert second["in_minutes"] == 12
    assert second["line"] == "IC"


async def test_departures_for_a_stop_given_by_id(hass: HomeAssistant, actions: FakeApi) -> None:
    response = await _call(hass, "get_departures", station="8507000", limit=3, transportations=["tram", "bus"])
    assert actions.requests(LOCATIONS_URL) == []
    query = actions.requests(BOARD_URL)[0][1].query
    assert (query["id"], query["limit"]) == ("8507000", "3")
    assert query.getall("transportations") == ["tram", "bus"]
    assert response["station_name"] == "Bern"
    assert len(response["departures"]) == 2


async def test_found_stop_names_the_board_when_the_answer_does_not(hass: HomeAssistant, actions: FakeApi) -> None:
    actions.board = board(name=None)
    assert (await _call(hass, "get_departures", station="Bern"))["station_name"] == "Bern"
    assert (await _call(hass, "get_departures", station="8507000"))["station_name"] is None


async def test_departure_that_just_left_counts_zero_minutes(hass: HomeAssistant, actions: FakeApi) -> None:
    actions.board = board([departure(-0.5), departure(0.9)])
    response = await _call(hass, "get_departures", station="8507000")
    assert [dep["in_minutes"] for dep in response["departures"]] == [0, 0]


async def test_unknown_stop_is_a_validation_error(hass: HomeAssistant, actions: FakeApi) -> None:
    with pytest.raises(ServiceValidationError) as error:
        await _call(hass, "get_departures", station="Atlantis")
    assert error.value.translation_domain == DOMAIN
    assert error.value.translation_key == "station_not_found"
    assert error.value.translation_placeholders == {"station": "Atlantis"}
    assert actions.requests(BOARD_URL) == []


@pytest.mark.parametrize("failure", [aiohttp.ClientConnectionError(), TimeoutError(), 500])
async def test_unreachable_station_search_is_reported(hass: HomeAssistant, actions: FakeApi, failure) -> None:
    actions.fail["locations"] = failure
    with pytest.raises(HomeAssistantError) as error:
        await _call(hass, "get_departures", station="Bern")
    assert error.value.translation_key == "api_unreachable"
    assert not isinstance(error.value, ServiceValidationError)


@pytest.mark.parametrize(
    ("failure", "key"),
    [(429, "rate_limited"), (500, "api_unreachable"), (TimeoutError(), "api_unreachable"), (aiohttp.ClientConnectionError(), "api_unreachable")],
)
async def test_failing_board_request_is_reported(hass: HomeAssistant, actions: FakeApi, failure, key: str) -> None:
    actions.fail["board"] = failure
    with pytest.raises(HomeAssistantError) as error:
        await _call(hass, "get_departures", station="8507000")
    assert error.value.translation_domain == DOMAIN
    assert error.value.translation_key == key


async def test_departure_limit_outside_the_range_is_refused(hass: HomeAssistant, actions: FakeApi) -> None:
    with pytest.raises(vol.Invalid):
        await _call(hass, "get_departures", station="8507000", limit=41)
    with pytest.raises(vol.Invalid):
        await _call(hass, "get_departures", station="8507000", transportations=["rocket"])
    assert actions.requests(BOARD_URL) == []


async def test_connections_between_two_stops_given_by_name(hass: HomeAssistant, actions: FakeApi) -> None:
    actions.connections = connections([connection(36, arrival=False), connection(6, delay=3)])
    response = await _call(hass, "get_connections", **{"from": "Bern", "to": "Thun"})

    query = actions.requests(CONNECTIONS_URL)[0][1].query
    assert (query["from"], query["to"], query["limit"]) == ("8507000", "8507100", "6")
    assert (response["from_name"], response["to_name"]) == ("Bern", "Thun")
    first, second = response["connections"]
    assert _unix(first["departure"]) == ts(6)
    assert _unix(first["arrival"]) == ts(26)
    assert first["in_minutes"] == 6
    assert first["duration_min"] == 20
    assert first["transfers"] == 0
    assert first["delay"] == 3
    assert (first["dep_platform"], first["arr_platform"]) == ("4", "2")
    assert first["products"] == ["IC 6"]
    assert first["legs"][0]["line"] == "IC"
    assert first["changes"] == []
    assert second["in_minutes"] == 36
    assert second["arrival"] is None


async def test_connections_between_two_stops_given_by_id(hass: HomeAssistant, actions: FakeApi) -> None:
    actions.connections = connections(named=False)
    response = await _call(hass, "get_connections", **{"from": "8507000", "to": "8507100", "limit": 2})
    assert actions.requests(LOCATIONS_URL) == []
    assert actions.requests(CONNECTIONS_URL)[0][1].query["limit"] == "2"
    assert (response["from_name"], response["to_name"]) == (None, None)
    assert len(response["connections"]) == 2


async def test_found_stops_name_the_route_when_the_answer_does_not(hass: HomeAssistant, actions: FakeApi) -> None:
    actions.connections = connections(named=False)
    response = await _call(hass, "get_connections", **{"from": "bern", "to": "thun"})
    assert (response["from_name"], response["to_name"]) == ("Bern", "Thun")


async def test_unknown_destination_is_a_validation_error(hass: HomeAssistant, actions: FakeApi) -> None:
    with pytest.raises(ServiceValidationError) as error:
        await _call(hass, "get_connections", **{"from": "Bern", "to": "Atlantis"})
    assert error.value.translation_key == "station_not_found"
    assert error.value.translation_placeholders == {"station": "Atlantis"}
    assert actions.requests(CONNECTIONS_URL) == []


@pytest.mark.parametrize(("failure", "key"), [(429, "rate_limited"), (503, "api_unreachable"), (TimeoutError(), "api_unreachable")])
async def test_failing_connection_request_is_reported(hass: HomeAssistant, actions: FakeApi, failure, key: str) -> None:
    actions.fail["connections"] = failure
    with pytest.raises(HomeAssistantError) as error:
        await _call(hass, "get_connections", **{"from": "8507000", "to": "8507100"})
    assert error.value.translation_key == key


async def test_connection_limit_outside_the_range_is_refused(hass: HomeAssistant, actions: FakeApi) -> None:
    with pytest.raises(vol.Invalid):
        await _call(hass, "get_connections", **{"from": "8507000", "to": "8507100", "limit": 13})
    assert actions.requests(CONNECTIONS_URL) == []


async def test_actions_only_answer_with_response_data(hass: HomeAssistant, actions: FakeApi) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "get_departures", {"station": "8507000"}, blocking=True)


async def test_registering_the_actions_again_keeps_the_existing_ones(hass: HomeAssistant, actions: FakeApi) -> None:
    before = dict(hass.services.async_services_for_domain(DOMAIN))
    async_register_services(hass)
    after = hass.services.async_services_for_domain(DOMAIN)
    assert set(after) == {"get_departures", "get_connections"}
    assert all(after[name] is before[name] for name in before)
