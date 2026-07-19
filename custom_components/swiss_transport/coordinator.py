"""DataUpdateCoordinator for the Swiss Transport departure board.

Fetches the stationboard (upcoming departures) for one station from the
public opendata.ch transport API. No authentication required.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_BASE,
    CONF_LIMIT,
    CONF_STATION_ID,
    CONF_TRANSPORTATIONS,
    DEFAULT_LIMIT,
    DOMAIN,
    FETCH_TIMEOUT_SECONDS,
    UPDATE_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
# Nominatim asks for a descriptive User-Agent identifying the application.
_GEOCODE_HEADERS = {"User-Agent": "ha-swiss-transport (Home Assistant integration)"}


async def async_reverse_geocode(hass: HomeAssistant, lat: float, lon: float) -> str | None:
    """Resolve a station's coordinates to a short human address
    ('Tannwaldstrasse, 4600 Olten') via OpenStreetMap Nominatim. Called at
    most once per station (cached in the coordinator), so it stays well
    within Nominatim's usage policy. Returns None on any failure — the card
    simply omits the line then."""
    session = async_get_clientsession(hass)
    params = {
        "lat": f"{lat}",
        "lon": f"{lon}",
        "format": "json",
        "zoom": "16",
        "addressdetails": "1",
    }
    try:
        async with session.get(
            NOMINATIM_URL, params=params, headers=_GEOCODE_HEADERS, timeout=FETCH_TIMEOUT_SECONDS
        ) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
    except Exception:  # noqa: BLE001 - geocoding is best-effort, never fatal
        return None
    addr = data.get("address") or {}
    road = addr.get("road") or addr.get("pedestrian") or addr.get("neighbourhood")
    postcode = addr.get("postcode")
    town = addr.get("town") or addr.get("city") or addr.get("village") or addr.get("municipality")
    place = " ".join(p for p in [postcode, town] if p).strip()
    parts = [p for p in [road, place] if p]
    return ", ".join(parts) or None


async def async_search_stations(hass: HomeAssistant, query: str) -> list[dict]:
    """Search stations by name for the config flow. Returns a list of
    {id, name, latitude, longitude}."""
    session = async_get_clientsession(hass)
    params = {"query": query, "type": "station"}
    async with session.get(
        f"{API_BASE}/locations", params=params, timeout=FETCH_TIMEOUT_SECONDS
    ) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    result = []
    for s in data.get("stations", []):
        if not s.get("id") or not s.get("name"):
            continue
        coord = s.get("coordinate") or {}
        result.append(
            {
                "id": s["id"],
                "name": s["name"],
                "latitude": coord.get("x"),
                "longitude": coord.get("y"),
            }
        )
    return result


def _parse_departure(entry: dict) -> dict | None:
    """Flatten one stationboard entry into a compact departure dict."""
    stop = entry.get("stop") or {}
    ts = stop.get("departureTimestamp")
    if not ts:
        return None
    category = (entry.get("category") or "").strip()
    number = (entry.get("number") or "").strip()
    # Line label: for trains the category already carries the product (S, IC,
    # IR, RE), the number is the run id and not user-facing; for bus/tram the
    # number IS the line, so combine them.
    if category in ("B", "T", "BUS", "TRM", "NFB", "NFT") and number:
        line = number
    elif category and number and not number.isdigit():
        line = f"{category}{number}"
    else:
        line = category or number or "?"

    delay = stop.get("delay")
    return {
        "line": line,
        "category": category,
        "number": number,
        "to": entry.get("to"),
        "operator": entry.get("operator"),
        "departure": stop.get("departure"),
        "departure_ts": int(ts),
        "delay": int(delay) if isinstance(delay, (int, float)) else None,
        "platform": stop.get("platform"),
        # Prognosis platform differs from the scheduled one on a track change.
        "platform_changed": bool(
            (stop.get("prognosis") or {}).get("platform")
            and (stop.get("prognosis") or {}).get("platform") != stop.get("platform")
        ),
    }


async def async_fetch_stationboard(
    hass: HomeAssistant, station_id: str, limit: int, transportations: list[str] | None
) -> dict:
    """Fetch the stationboard for one station."""
    session = async_get_clientsession(hass)
    params = {"id": station_id, "limit": str(limit)}
    if transportations:
        # The API accepts the parameter repeated once per type.
        params["transportations"] = transportations
    async with session.get(
        f"{API_BASE}/stationboard", params=params, timeout=FETCH_TIMEOUT_SECONDS
    ) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)

    station = data.get("station") or {}
    coord = station.get("coordinate") or {}
    departures = []
    for entry in data.get("stationboard", []):
        try:
            dep = _parse_departure(entry)
        except Exception:  # noqa: BLE001 - one malformed entry must never kill the refresh
            _LOGGER.debug("Skipping malformed stationboard entry", exc_info=True)
            continue
        if dep is not None:
            departures.append(dep)
    departures.sort(key=lambda d: d["departure_ts"])
    return {
        "station_id": station.get("id") or station_id,
        "station_name": station.get("name"),
        "latitude": coord.get("x"),
        "longitude": coord.get("y"),
        "departures": departures,
    }


def _duration_to_minutes(value) -> int | None:
    """'00d00:27:00' -> 27 (total minutes)."""
    try:
        days, rest = str(value).split("d")
        h, m, s = rest.split(":")
        return int(days) * 1440 + int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _parse_connection(con: dict) -> dict | None:
    frm = con.get("from") or {}
    to = con.get("to") or {}
    dep_ts = frm.get("departureTimestamp")
    if not dep_ts:
        return None
    dep_delay = frm.get("delay")
    legs = []
    for sec in con.get("sections") or []:
        journey = sec.get("journey")
        if not journey:
            continue  # walking section
        legs.append(
            {
                "line": f"{(journey.get('category') or '').strip()}{(journey.get('number') or '').strip()}"
                if journey.get("number") and not str(journey.get("number")).isdigit()
                else (journey.get("category") or "").strip() or (journey.get("number") or ""),
                "category": (journey.get("category") or "").strip(),
                "number": (journey.get("number") or "").strip(),
                "to": journey.get("to"),
            }
        )
    return {
        "departure": frm.get("departure"),
        "departure_ts": int(dep_ts),
        "dep_platform": frm.get("platform"),
        "delay": int(dep_delay) if isinstance(dep_delay, (int, float)) else None,
        "arrival": to.get("arrival"),
        "arrival_ts": int(to["arrivalTimestamp"]) if to.get("arrivalTimestamp") else None,
        "arr_platform": to.get("platform"),
        "duration_min": _duration_to_minutes(con.get("duration")),
        "transfers": con.get("transfers"),
        "products": con.get("products") or [],
    }


async def async_fetch_connections(
    hass: HomeAssistant, from_id: str, to_id: str, limit: int
) -> dict:
    """Fetch upcoming connections between two stations."""
    session = async_get_clientsession(hass)
    params = {"from": from_id, "to": to_id, "limit": str(limit)}
    async with session.get(
        f"{API_BASE}/connections", params=params, timeout=FETCH_TIMEOUT_SECONDS
    ) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    connections = []
    for con in data.get("connections", []):
        try:
            parsed = _parse_connection(con)
        except Exception:  # noqa: BLE001 - one malformed connection must never kill the refresh
            _LOGGER.debug("Skipping malformed connection", exc_info=True)
            continue
        if parsed is not None:
            connections.append(parsed)
    connections.sort(key=lambda c: c["departure_ts"])
    frm = (data.get("from") or {})
    to = (data.get("to") or {})
    return {
        "from_name": frm.get("name"),
        "to_name": to.get("name"),
        "connections": connections,
    }


class SwissTransportCoordinator(DataUpdateCoordinator[dict]):
    """Fetches the departure board for one configured station."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self._entry = entry
        self._address: str | None = None  # resolved once, then cached

    async def _async_update_data(self) -> dict:
        data = self._entry.data
        options = self._entry.options
        limit = options.get(CONF_LIMIT, data.get(CONF_LIMIT, DEFAULT_LIMIT))
        transportations = options.get(
            CONF_TRANSPORTATIONS, data.get(CONF_TRANSPORTATIONS)
        ) or None
        try:
            result = await async_fetch_stationboard(
                self.hass, data[CONF_STATION_ID], limit, transportations
            )
        except Exception as err:
            raise UpdateFailed(f"transport.opendata.ch unreachable: {err}") from err

        # Resolve the station address once (best-effort). Retried on later
        # polls only until it succeeds, so a transient geocoder hiccup isn't
        # permanent but Nominatim is never hammered.
        if self._address is None and result.get("latitude") is not None:
            self._address = await async_reverse_geocode(
                self.hass, result["latitude"], result["longitude"]
            )
        result["address"] = self._address
        return result


class SwissConnectionCoordinator(DataUpdateCoordinator[dict]):
    """Fetches upcoming connections for one saved from -> to route."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self._entry = entry

    async def _async_update_data(self) -> dict:
        from .const import (  # local import avoids a cycle at module load
            CONF_FROM_ID,
            CONF_LIMIT,
            CONF_TO_ID,
            DEFAULT_CONNECTION_LIMIT,
        )

        data = self._entry.data
        limit = self._entry.options.get(CONF_LIMIT, data.get(CONF_LIMIT, DEFAULT_CONNECTION_LIMIT))
        try:
            return await async_fetch_connections(
                self.hass, data[CONF_FROM_ID], data[CONF_TO_ID], limit
            )
        except Exception as err:
            raise UpdateFailed(f"transport.opendata.ch unreachable: {err}") from err
