"""DataUpdateCoordinator for the Swiss Transport departure board.

Fetches the stationboard (upcoming departures) for one station from the
public opendata.ch transport API. No authentication required.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_BASE,
    CONF_LIMIT,
    CONF_OJP_TOKEN,
    CONF_STATION_ID,
    CONF_TRANSPORTATIONS,
    DEFAULT_LIMIT,
    DOMAIN,
    FETCH_TIMEOUT_SECONDS,
    OJP_ENDPOINT,
    OJP_REQUESTOR_REF,
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


# --- Optional real-time enrichment via opentransportdata.swiss OJP 2.0 ---

_OJP_NS = {"o": "http://www.vdv.de/ojp", "s": "http://www.siri.org.uk/siri"}

# SIRI occupancy levels mapped to a coarse 1 (low) .. 3 (high) scale that the
# card can render, tolerant of the various spellings different feeds use.
_OCCUPANCY_LEVEL = {
    "manyseatsavailable": 1,
    "low": 1,
    "seatsavailable": 1,
    "fewseatsavailable": 2,
    "medium": 2,
    "standingroomonly": 3,
    "full": 3,
    "high": 3,
    "crushedstandingroomonly": 3,
}


def _ojp_iso_to_ts(value) -> int | None:
    """OJP time ('2026-07-19T21:32:00Z') -> unix seconds."""
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except (ValueError, AttributeError, TypeError):
        return None


def _build_stop_event_request(station_id: str, limit: int) -> str:
    """Minimal OJP 2.0 StopEventRequest for one stop, with real-time data."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<OJP xmlns="http://www.vdv.de/ojp" xmlns:siri="http://www.siri.org.uk/siri" version="2.0">'
        "<OJPRequest><siri:ServiceRequest>"
        f"<siri:RequestTimestamp>{ts}</siri:RequestTimestamp>"
        f"<siri:RequestorRef>{OJP_REQUESTOR_REF}</siri:RequestorRef>"
        "<OJPStopEventRequest>"
        f"<siri:RequestTimestamp>{ts}</siri:RequestTimestamp>"
        "<Location><PlaceRef>"
        f"<siri:StopPointRef>{station_id}</siri:StopPointRef>"
        "</PlaceRef></Location>"
        "<Params>"
        f"<NumberOfResults>{int(limit)}</NumberOfResults>"
        "<StopEventType>departure</StopEventType>"
        "<IncludeRealtimeData>true</IncludeRealtimeData>"
        "</Params>"
        "</OJPStopEventRequest>"
        "</siri:ServiceRequest></OJPRequest></OJP>"
    )


def _txt(elem, path: str) -> str | None:
    node = elem.find(path, _OJP_NS)
    return node.text if node is not None else None


def _parse_ojp_stationboard(xml_text: str) -> dict:
    """Turn an OJP StopEventResponse into
    {"events": {timetabled_ts: [event, ...]}, "alerts": [text, ...]}.

    Each event carries the fresher real-time facts we overlay onto the
    opendata.ch board: estimated time, cancellation, platform change and
    occupancy. Matching is done on the scheduled (timetabled) departure
    time, which is identical in both sources."""
    root = ET.fromstring(xml_text)

    # Station-wide disruption texts, de-duplicated. The human-readable summary
    # lives at PassengerInformationAction/TextualContent/SummaryContent/
    # SummaryText — all in the SIRI namespace, with the text directly on the
    # SummaryText element.
    alerts: list[str] = []
    for sit in root.findall(".//o:PtSituation", _OJP_NS):
        text = _txt(sit, ".//s:SummaryContent/s:SummaryText") or _txt(sit, ".//s:SummaryText")
        if text:
            text = text.strip()
            if text and text not in alerts:
                alerts.append(text)

    events: dict[int, list[dict]] = {}
    for r in root.findall(".//o:StopEventResult", _OJP_NS):
        planned = _ojp_iso_to_ts(_txt(r, ".//o:ServiceDeparture/o:TimetabledTime"))
        if planned is None:
            continue
        estimated = _ojp_iso_to_ts(_txt(r, ".//o:ServiceDeparture/o:EstimatedTime"))
        planned_quay = _txt(r, ".//o:PlannedQuay/o:Text")
        estimated_quay = _txt(r, ".//o:EstimatedQuay/o:Text")
        cancelled = (_txt(r, ".//o:Cancelled") or "").lower() == "true"

        occupancy = None
        for occ in r.findall(".//o:ExpectedDepartureOccupancy", _OJP_NS):
            level = (_txt(occ, "o:OccupancyLevel") or "").strip().lower()
            mapped = _OCCUPANCY_LEVEL.get(level.replace(" ", ""))
            if mapped is not None:
                occupancy = max(occupancy or 0, mapped)

        events.setdefault(planned, []).append(
            {
                "destination": (_txt(r, ".//o:DestinationText/o:Text") or "").strip(),
                "estimated_ts": estimated,
                "cancelled": cancelled,
                "planned_quay": planned_quay,
                "estimated_quay": estimated_quay,
                "occupancy": occupancy,
            }
        )
    return {"events": events, "alerts": alerts}


async def async_fetch_ojp_stationboard(
    hass: HomeAssistant, token: str, station_id: str, limit: int
) -> dict:
    """POST an OJP StopEventRequest and parse the response. Raises on failure;
    callers treat enrichment as best-effort and fall back to opendata.ch."""
    session = async_get_clientsession(hass)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/xml",
    }
    body = _build_stop_event_request(station_id, limit)
    async with session.post(
        OJP_ENDPOINT, data=body.encode("utf-8"), headers=headers, timeout=FETCH_TIMEOUT_SECONDS
    ) as resp:
        resp.raise_for_status()
        text = await resp.text()
    return _parse_ojp_stationboard(text)


def _apply_ojp(board: dict, ojp: dict) -> None:
    """Overlay OJP real-time facts onto the opendata.ch board in place."""
    events = ojp.get("events") or {}
    for dep in board.get("departures", []):
        matches = events.get(dep["departure_ts"])
        if not matches:
            continue
        # Disambiguate several departures at the same minute by destination.
        match = None
        if len(matches) == 1:
            match = matches[0]
        else:
            to = (dep.get("to") or "").strip().lower()
            for m in matches:
                if m["destination"].lower() == to:
                    match = m
                    break
            match = match or matches[0]

        dep["cancelled"] = match["cancelled"]
        if match.get("occupancy"):
            dep["occupancy"] = match["occupancy"]
        # Fresher, second-accurate delay from the estimated time.
        if match.get("estimated_ts"):
            dep["delay"] = max(0, round((match["estimated_ts"] - dep["departure_ts"]) / 60))
        # Platform change from the effective quay.
        eq = (match.get("estimated_quay") or "").strip()
        pq = (match.get("planned_quay") or dep.get("platform") or "").strip()
        if eq and eq != pq:
            dep["platform_changed"] = True
            dep["platform"] = eq
    board["alerts"] = ojp.get("alerts") or []
    board["realtime"] = True


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
    # Break the journey into legs (skip walking sections), keeping the from/to
    # station names and platforms of each ridden train.
    legs = []
    for sec in con.get("sections") or []:
        journey = sec.get("journey")
        if not journey:
            continue  # walking section
        cat = (journey.get("category") or "").strip()
        num = (journey.get("number") or "").strip()
        line = f"{cat}{num}" if num and not str(num).isdigit() else (cat or num or "")
        sec_dep = sec.get("departure") or {}
        sec_arr = sec.get("arrival") or {}
        legs.append(
            {
                "line": line,
                "category": cat,
                "number": num,
                "to": journey.get("to"),
                "from_name": (sec_dep.get("station") or {}).get("name"),
                "from_platform": sec_dep.get("platform"),
                "to_name": (sec_arr.get("station") or {}).get("name"),
                "to_platform": sec_arr.get("platform"),
            }
        )
    # Transfer points: where one leg ends and the next begins — the station to
    # change at, with the arrival and onward-departure platforms.
    changes = [
        {
            "station": legs[i]["to_name"],
            "arr_platform": legs[i]["to_platform"],
            "dep_platform": legs[i + 1]["from_platform"],
        }
        for i in range(len(legs) - 1)
    ]
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
        "legs": legs,
        "changes": changes,
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


def _resolve_ojp_token(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """The optional OJP real-time token. Read from this entry first, then from
    any sibling entry that has one — so it need only be entered once and then
    enriches every station board."""
    own = (entry.options.get(CONF_OJP_TOKEN) or entry.data.get(CONF_OJP_TOKEN) or "").strip()
    if own:
        return own
    for other in hass.config_entries.async_entries(DOMAIN):
        tok = (other.options.get(CONF_OJP_TOKEN) or other.data.get(CONF_OJP_TOKEN) or "").strip()
        if tok:
            return tok
    return None


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

        # Optional real-time enrichment (opentransportdata.swiss OJP). Strictly
        # best-effort: any failure leaves the opendata.ch board untouched.
        token = _resolve_ojp_token(self.hass, self._entry)
        if token:
            try:
                ojp = await async_fetch_ojp_stationboard(
                    self.hass, token, data[CONF_STATION_ID], limit
                )
                _apply_ojp(result, ojp)
            except Exception:  # noqa: BLE001 - enrichment must never break the board
                _LOGGER.debug("OJP real-time enrichment failed", exc_info=True)

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
