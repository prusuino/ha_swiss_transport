"""Actions with response data: look up departures and connections on demand.

The sensors cover the stops and routes a user configured. These actions
answer ad-hoc questions from scripts, automations and Assist: the next
departures at any stop, the next connections between any two stops. They
call the same public transport.opendata.ch endpoints as the sensors and
return the same flattened records, plus an `in_minutes` countdown.

A stop may be given by name or by its numeric id; a name is resolved with
the API's station search and the first match is used (the response names
the stop that was actually found).
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import aiohttp
import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DEFAULT_CONNECTION_LIMIT, DEFAULT_LIMIT, DOMAIN, MAX_CONNECTION_LIMIT, TRANSPORT_TYPES
from .coordinator import async_fetch_connections, async_fetch_stationboard, async_search_stations

SERVICE_GET_DEPARTURES = "get_departures"
SERVICE_GET_CONNECTIONS = "get_connections"

ATTR_STATION = "station"
ATTR_FROM = "from"
ATTR_TO = "to"
ATTR_LIMIT = "limit"
ATTR_TRANSPORTATIONS = "transportations"

MAX_BOARD_LIMIT = 40

GET_DEPARTURES_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_STATION): cv.string,
        vol.Optional(ATTR_LIMIT, default=DEFAULT_LIMIT): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_BOARD_LIMIT)),
        vol.Optional(ATTR_TRANSPORTATIONS): vol.All(cv.ensure_list, [vol.In(TRANSPORT_TYPES)]),
    }
)

GET_CONNECTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_FROM): cv.string,
        vol.Required(ATTR_TO): cv.string,
        vol.Optional(ATTR_LIMIT, default=DEFAULT_CONNECTION_LIMIT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_CONNECTION_LIMIT)
        ),
    }
)


def _iso(ts: int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat()


def _in_minutes(ts: int | None, now: float) -> int | None:
    if ts is None:
        return None
    return max(0, int((ts - now) // 60))


async def _resolve_station(hass: HomeAssistant, value: str) -> dict:
    """A stop by id or name -> {id, name}. Names go through the station
    search; the first match wins, as it does in the config flow."""
    value = value.strip()
    if value.isdigit():
        return {"id": value, "name": None}
    try:
        stations = await async_search_stations(hass, value)
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="api_unreachable"
        ) from err
    if not stations:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="station_not_found",
            translation_placeholders={"station": value},
        )
    return {"id": stations[0]["id"], "name": stations[0]["name"]}


def _raise_for_api(err: Exception) -> None:
    if isinstance(err, aiohttp.ClientResponseError) and err.status == 429:
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="rate_limited") from err
    raise HomeAssistantError(translation_domain=DOMAIN, translation_key="api_unreachable") from err


async def _get_departures(call: ServiceCall) -> ServiceResponse:
    hass = call.hass
    station = await _resolve_station(hass, call.data[ATTR_STATION])
    try:
        board = await async_fetch_stationboard(
            hass, station["id"], call.data[ATTR_LIMIT], call.data.get(ATTR_TRANSPORTATIONS)
        )
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        _raise_for_api(err)
    now = time.time()
    departures = []
    for dep in board["departures"]:
        departures.append(
            {
                "line": dep["line"],
                "category": dep["category"],
                "number": dep["number"],
                "to": dep["to"],
                "operator": dep["operator"],
                "departure": _iso(dep["departure_ts"]),
                "in_minutes": _in_minutes(dep["departure_ts"], now),
                "delay": dep["delay"],
                "platform": dep["platform"],
                "platform_changed": dep["platform_changed"],
            }
        )
    return {
        "station_id": board["station_id"],
        "station_name": board["station_name"] or station["name"],
        "departures": departures,
    }


async def _get_connections(call: ServiceCall) -> ServiceResponse:
    hass = call.hass
    frm, to = await asyncio.gather(
        _resolve_station(hass, call.data[ATTR_FROM]), _resolve_station(hass, call.data[ATTR_TO])
    )
    try:
        result = await async_fetch_connections(hass, frm["id"], to["id"], call.data[ATTR_LIMIT])
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        _raise_for_api(err)
    now = time.time()
    connections = []
    for con in result["connections"]:
        connections.append(
            {
                "departure": _iso(con["departure_ts"]),
                "in_minutes": _in_minutes(con["departure_ts"], now),
                "arrival": _iso(con["arrival_ts"]),
                "duration_min": con["duration_min"],
                "transfers": con["transfers"],
                "delay": con["delay"],
                "dep_platform": con["dep_platform"],
                "arr_platform": con["arr_platform"],
                "products": con["products"],
                "legs": con["legs"],
                "changes": con["changes"],
            }
        )
    return {
        "from_name": result["from_name"] or frm["name"],
        "to_name": result["to_name"] or to["name"],
        "connections": connections,
    }


def async_register_services(hass: HomeAssistant) -> None:
    """Register the actions once per Home Assistant run."""
    if hass.services.has_service(DOMAIN, SERVICE_GET_DEPARTURES):
        return
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_DEPARTURES,
        _get_departures,
        schema=GET_DEPARTURES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_CONNECTIONS,
        _get_connections,
        schema=GET_CONNECTIONS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
