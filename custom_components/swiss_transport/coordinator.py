"""DataUpdateCoordinator for the Swiss Transport departure board.

Fetches the stationboard (upcoming departures) for one station from the
public transport.opendata.ch API. No authentication required.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .issues import IssueReporter
from .const import (
    API_BASE,
    CONF_LIMIT,
    CONF_LINE_LABEL,
    CONF_DIRECTIONS,
    CONF_OJP_TOKEN,
    CONF_STATION_ID,
    CONF_TRANSPORTATIONS,
    CONNECTION_UPDATE_INTERVAL_SECONDS,
    DEFAULT_LIMIT,
    DIRECTION_FETCH_FACTOR,
    DIRECTION_FETCH_MAX,
    DEFAULT_LINE_LABEL,
    DOMAIN,
    FETCH_TIMEOUT_SECONDS,
    LINE_LABEL_NUMBER,
    LINE_LABEL_CATEGORY,
    OJP_ENDPOINT,
    OJP_REQUESTOR_REF,
    RATE_LIMIT_BACKOFF_SECONDS,
    UPDATE_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
# Nominatim asks for a descriptive User-Agent identifying the application.
_GEOCODE_HEADERS = {"User-Agent": "ha-swiss-transport (Home Assistant integration)"}


async def async_reverse_geocode(hass: HomeAssistant, lat: float, lon: float) -> str | None:
    """Resolve a station's coordinates to a short human address
    ('Hirschengraben, 3011 Bern') via OpenStreetMap Nominatim. Called at
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


_LOCAL_CATEGORIES = ("B", "T", "BUS", "TRM", "NFB", "NFT")


def _line_label(category: str, number: str, mode: str = DEFAULT_LINE_LABEL) -> str:
    """User-facing line label from the API's category and number.

    Bus and tram show the number alone ("34"). For trains the number is the
    line number (S 9, IC 8) and the run id lives in `name`; `mode` decides:
    "category" keeps only the category ("S", a purely numeric number counts as
    run id), "full" prefixes it ("S9") and "number" shows only the number ("9").
    A zero-padded number is a run id in every mode (ICE "000070"), so only the
    category remains.
    """
    if category in _LOCAL_CATEGORIES and number:
        return number
    if not number or (number.isdigit() and number.startswith("0")):
        return category or number
    if mode == LINE_LABEL_NUMBER:
        return number
    if mode == LINE_LABEL_CATEGORY and number.isdigit():
        return category or number
    return f"{category}{number}"


def _capacity_level(entry: dict) -> int | None:
    """Expected occupancy of a journey on the 1 (low) .. 3 (high) scale the
    card renders: the fuller of the two classes, as the API forecasts it in
    `capacity1st` / `capacity2nd`. None when it has no forecast."""
    levels = [
        level
        for level in (entry.get("capacity1st"), entry.get("capacity2nd"))
        if isinstance(level, int) and not isinstance(level, bool) and 1 <= level <= 3
    ]
    return max(levels) if levels else None


def _parse_departure(entry: dict, line_label: str = DEFAULT_LINE_LABEL) -> dict | None:
    """Flatten one stationboard entry into a compact departure dict."""
    stop = entry.get("stop") or {}
    ts = stop.get("departureTimestamp")
    if not ts:
        return None
    category = (entry.get("category") or "").strip()
    number = (entry.get("number") or "").strip()
    line = _line_label(category, number, line_label) or "?"

    delay = stop.get("delay")
    dep = {
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
        # The board is asked for with showCancelled=1: a journey that does not
        # run, or passes this stop without calling, stays on it and is marked.
        "cancelled": entry.get("cancelled") is True,
    }
    occupancy = _capacity_level(entry)
    if occupancy is not None:
        dep["occupancy"] = occupancy
    return dep


def _parse_board(data: dict, line_label: str = DEFAULT_LINE_LABEL) -> list[dict]:
    """Flatten and sort the departures of one stationboard answer."""
    departures = []
    for entry in data.get("stationboard", []):
        try:
            dep = _parse_departure(entry, line_label)
        except Exception:  # noqa: BLE001 - one malformed entry must never kill the refresh
            _LOGGER.debug("Skipping malformed stationboard entry", exc_info=True)
            continue
        if dep is not None:
            departures.append(dep)
    departures.sort(key=lambda d: d["departure_ts"])
    return departures


async def _async_get_board(session, params: dict) -> dict:
    async with session.get(
        f"{API_BASE}/stationboard", params=params, timeout=FETCH_TIMEOUT_SECONDS
    ) as resp:
        resp.raise_for_status()
        return await resp.json(content_type=None)


async def async_fetch_stationboard(
    hass: HomeAssistant,
    station_id: str,
    limit: int,
    transportations: list[str] | None,
    line_label: str = DEFAULT_LINE_LABEL,
) -> dict:
    """Fetch the stationboard for one station."""
    session = async_get_clientsession(hass)
    # showCancelled keeps cancelled journeys on the board, each row then
    # carries `cancelled`; without it they are silently left out.
    params = {"id": station_id, "limit": str(limit), "showCancelled": "1"}
    if transportations:
        # The API accepts the parameter repeated once per type.
        params["transportations"] = transportations
    data = await _async_get_board(session, params)
    departures = _parse_board(data, line_label)

    station = data.get("station") or {}
    coord = station.get("coordinate") or {}
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


def _minute(ts: int) -> int:
    """A unix time cut to the full minute."""
    return ts - ts % 60


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
    occupancy. Matching is done on the minute of the scheduled (timetabled)
    departure: opendata.ch gives it to the minute, the OJP answer to the
    second for many tram and bus lines (07:42:24), so the keys are the
    scheduled times cut to the minute (`_minute`)."""
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

        # OJP 2.0 takes the occupancy elements from SIRI; an answer that
        # writes them in the OJP namespace is read as well.
        occupancy = None
        for occ in r.findall(".//s:ExpectedDepartureOccupancy", _OJP_NS) + r.findall(
            ".//o:ExpectedDepartureOccupancy", _OJP_NS
        ):
            level = (_txt(occ, "s:OccupancyLevel") or _txt(occ, "o:OccupancyLevel") or "").strip().lower()
            mapped = _OCCUPANCY_LEVEL.get(level.replace(" ", ""))
            if mapped is not None:
                occupancy = max(occupancy or 0, mapped)

        events.setdefault(_minute(planned), []).append(
            {
                "destination": (_txt(r, ".//o:DestinationText/o:Text") or "").strip(),
                "planned_ts": planned,
                "direction_id": _direction_id(
                    _txt(r, ".//o:Service/o:PublishedServiceName/o:Text"), _txt(r, ".//o:Service/s:DirectionRef")
                ),
                "estimated_ts": estimated,
                "cancelled": cancelled,
                "planned_quay": planned_quay,
                "estimated_quay": estimated_quay,
                "occupancy": occupancy,
            }
        )
    return {"events": events, "alerts": alerts}


def _direction_id(line: str | None, direction: str | None) -> str | None:
    """The id of a line in one direction, "<line>|<direction>" ("6|H"), or
    None when the answer names no direction for the journey."""
    line, direction = (line or "").strip(), (direction or "").strip()
    return f"{line}|{direction}" if line and direction else None


def direction_choices(ojp: dict) -> dict[str, str]:
    """The lines and directions of a parsed OJP answer, for choosing from:
    id -> "<line> → <most frequent destination>", ordered by line. Where the
    stop has named Haltekanten (the large ones: "A", "D", a track number),
    the one most journeys of that direction leave from is added ("· D"), so
    the side of the street can be recognised."""
    destinations: dict[str, dict[str, int]] = {}
    quays: dict[str, dict[str, int]] = {}
    for matches in (ojp.get("events") or {}).values():
        for event in matches:
            key = event.get("direction_id")
            if not key:
                continue
            counts = destinations.setdefault(key, {})
            counts[event["destination"]] = counts.get(event["destination"], 0) + 1
            quay = (event.get("planned_quay") or "").strip()
            if quay:
                quays.setdefault(key, {})[quay] = quays.get(key, {}).get(quay, 0) + 1

    def order(key: str) -> tuple:
        line, _, direction = key.partition("|")
        digits = "".join(ch for ch in line if ch.isdigit())
        return (0, int(digits), line, direction) if digits else (1, 0, line, direction)

    choices: dict[str, str] = {}
    for key in sorted(destinations, key=order):
        counts = destinations[key]
        usual = max(counts, key=lambda name: (counts[name], name))
        label = f"{key.partition('|')[0]} → {usual}" if usual else key.partition("|")[0]
        if key in quays:
            label += " · " + max(quays[key], key=lambda name: (quays[key][name], name))
        choices[key] = label
    return choices


async def async_fetch_directions(hass: HomeAssistant, token: str, station_id: str) -> dict[str, str]:
    """The lines and directions that currently leave from a stop (see
    `direction_choices`). Raises like `async_fetch_ojp_stationboard`."""
    return direction_choices(await async_fetch_ojp_stationboard(hass, token, station_id, DIRECTION_FETCH_MAX))


class OjpAuthError(Exception):
    """opentransportdata.swiss rejected the OJP bearer token (HTTP 401/403)."""

    def __init__(self, status: int) -> None:
        super().__init__(f"opentransportdata.swiss rejected the OJP token (HTTP {status})")
        self.status = status


async def _async_ojp_post(hass: HomeAssistant, token: str, station_id: str, limit: int) -> str:
    """POST an OJP StopEventRequest and return the raw response body.

    Raises OjpAuthError when the token is rejected (HTTP 401/403) and the
    usual client errors for anything else."""
    session = async_get_clientsession(hass)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/xml",
    }
    body = _build_stop_event_request(station_id, limit)
    async with session.post(
        OJP_ENDPOINT, data=body.encode("utf-8"), headers=headers, timeout=FETCH_TIMEOUT_SECONDS
    ) as resp:
        if resp.status in (401, 403):
            raise OjpAuthError(resp.status)
        resp.raise_for_status()
        return await resp.text()


async def async_fetch_ojp_stationboard(
    hass: HomeAssistant, token: str, station_id: str, limit: int
) -> dict:
    """POST an OJP StopEventRequest and parse the response. Raises on failure
    (OjpAuthError for a rejected token); callers treat enrichment as
    best-effort and fall back to opendata.ch."""
    return _parse_ojp_stationboard(await _async_ojp_post(hass, token, station_id, limit))


async def async_validate_ojp_token(hass: HomeAssistant, token: str, station_id: str) -> None:
    """Probe opentransportdata.swiss once with the token — the config and
    options flows call this before storing it. Returns normally when the
    token is accepted; raises OjpAuthError when it is rejected (HTTP 401/403)
    and any other error when the endpoint cannot be reached."""
    await _async_ojp_post(hass, token, station_id, 1)


def _apply_ojp(board: dict, ojp: dict) -> None:
    """Overlay OJP real-time facts onto the opendata.ch board in place."""
    events = ojp.get("events") or {}
    for dep in board.get("departures", []):
        matches = events.get(_minute(dep["departure_ts"]))
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

        if match.get("direction_id"):
            dep["direction_id"] = match["direction_id"]
            dep["direction"] = match["direction_id"].rpartition("|")[2]
        # Cancelled when either source says so.
        dep["cancelled"] = bool(dep.get("cancelled")) or match["cancelled"]
        if match.get("occupancy"):
            dep["occupancy"] = match["occupancy"]
        # Fresher, second-accurate delay from the estimated time.
        if match.get("estimated_ts"):
            # against the real-time source's own scheduled time: measured
            # against the board's minute, a tram due at :54 and on time
            # would read as a minute late
            dep["delay"] = max(0, round((match["estimated_ts"] - match["planned_ts"]) / 60))
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


def _parse_connection(con: dict, line_label: str = DEFAULT_LINE_LABEL) -> dict | None:
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
        line = _line_label(cat, num, line_label)
        sec_dep = sec.get("departure") or {}
        sec_arr = sec.get("arrival") or {}
        legs.append(
            {
                "line": line,
                "category": cat,
                "number": num,
                "operator": journey.get("operator"),
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
        # Forecast departure time; null when the source has none.
        "departure_prognosis": (frm.get("prognosis") or {}).get("departure"),
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
    hass: HomeAssistant,
    from_id: str,
    to_id: str,
    limit: int,
    line_label: str = DEFAULT_LINE_LABEL,
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
            parsed = _parse_connection(con, line_label)
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


_REAUTH_ASKED = f"{DOMAIN}_token_reauth_asked"


def _async_start_token_reauth(hass: HomeAssistant, entry: ConfigEntry, token: str) -> None:
    """Ask for a new OJP token in the UI. The token is integration-wide, so
    one reauthentication per rejected token is enough: a second station board
    that sees the same rejection does not open another one. The marker is set
    here and not read from the open flows, because a flow that is still
    starting is not listed yet."""
    if hass.data.get(_REAUTH_ASKED) == token:
        return
    hass.data[_REAUTH_ASKED] = token
    entry.async_start_reauth(hass)


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


def _apply_rate_limit_backoff(
    coordinator: DataUpdateCoordinator, err: Exception, normal_seconds: int
) -> None:
    """Slow the poll right down after an HTTP 429.

    transport.opendata.ch has no fixed limit per client but throttles one
    that asks too often. While it does, every further poll is a wasted
    request, so back off; the coordinator restores its normal cadence with
    the next successful update.
    """
    if getattr(err, "status", None) != 429:
        coordinator.update_interval = timedelta(seconds=normal_seconds)
        return
    backoff = timedelta(seconds=RATE_LIMIT_BACKOFF_SECONDS)
    if coordinator.update_interval != backoff:
        _LOGGER.warning(
            "transport.opendata.ch rate limit hit (HTTP 429) — pausing polling "
            "for %d minutes",
            RATE_LIMIT_BACKOFF_SECONDS // 60,
        )
    coordinator.update_interval = backoff


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
        self.issues = IssueReporter(hass, entry.entry_id)
        self._address: str | None = None  # resolved once, then cached
        # True after the OJP token was rejected and the warning was logged;
        # cleared as soon as the token is accepted again.
        self._ojp_auth_failed = False
        # Direction filter: what the real-time answers have told so far about
        # which way a line with a given destination goes, (line label,
        # destination) -> direction id. It places the rows the real-time
        # answer does not cover (or all rows while it cannot be read).
        self._known_directions: dict[tuple[str, str], str] = {}

    def _filter_directions(self, board: dict, wanted: set[str], limit: int) -> None:
        """Keep the departures of the wanted lines and directions, in place.
        A departure of a wanted line whose direction is not known (yet)
        stays: showing one row too many is the smaller mistake than hiding
        a tram that runs. One of a line that is not wanted in any direction
        goes, whatever its direction would be."""
        departures = board.get("departures", [])
        # First learn from every row the real-time answer placed, then place
        # the others: the timetable board reaches further ahead than the
        # real-time answer, so the later rows of a line have no match.
        for dep in departures:
            if dep.get("direction_id"):
                self._known_directions[(dep.get("line") or "", dep.get("to") or "")] = dep["direction_id"]
        wanted_lines = {key.partition("|")[0] for key in wanted}
        kept = []
        for dep in departures:
            way = (dep.get("line") or "", dep.get("to") or "")
            if not dep.get("direction_id") and way in self._known_directions:
                dep["direction_id"] = self._known_directions[way]
                dep["direction"] = dep["direction_id"].rpartition("|")[2]
            if dep.get("direction_id"):
                if dep["direction_id"] in wanted:
                    kept.append(dep)
            elif wanted_lines & {dep.get("line"), dep.get("number"), f"{dep.get('category') or ''}{dep.get('number') or ''}"}:
                # the line as the board names it ("6", "S9") or as category
                # and number, which is how the real-time source names trains
                kept.append(dep)
        board["departures"] = kept[:limit]
        board["direction_filter"] = sorted(wanted)

    async def _async_update_data(self) -> dict:
        data = self._entry.data
        options = self._entry.options
        limit = options.get(CONF_LIMIT, data.get(CONF_LIMIT, DEFAULT_LIMIT))
        transportations = options.get(
            CONF_TRANSPORTATIONS, data.get(CONF_TRANSPORTATIONS)
        ) or None
        token = _resolve_ojp_token(self.hass, self._entry)
        # The direction filter needs the token (the direction comes from the
        # real-time answer); without one the whole stop is shown.
        wanted = set(options.get(CONF_DIRECTIONS) or []) if token else set()
        fetch_limit = min(limit * DIRECTION_FETCH_FACTOR, max(DIRECTION_FETCH_MAX, limit)) if wanted else limit
        try:
            result = await async_fetch_stationboard(
                self.hass,
                data[CONF_STATION_ID],
                fetch_limit,
                transportations,
                options.get(CONF_LINE_LABEL, DEFAULT_LINE_LABEL),
            )
        except Exception as err:
            _apply_rate_limit_backoff(self, err, UPDATE_INTERVAL_SECONDS)
            self.issues.failure("unreachable", {"host": "transport.opendata.ch"})
            raise UpdateFailed(f"transport.opendata.ch unreachable: {err}") from err
        self.issues.clear("unreachable")
        self.update_interval = timedelta(seconds=UPDATE_INTERVAL_SECONDS)

        # Optional real-time enrichment (opentransportdata.swiss OJP). Strictly
        # best-effort: any failure leaves the opendata.ch board untouched. A
        # rejected token is the one failure that is not transient, so it is
        # said once at WARNING level instead of disappearing into debug logs.
        if token:
            try:
                ojp = await async_fetch_ojp_stationboard(
                    self.hass, token, data[CONF_STATION_ID], fetch_limit
                )
                _apply_ojp(result, ojp)
            except OjpAuthError as err:
                if not self._ojp_auth_failed:
                    _LOGGER.warning(
                        "opentransportdata.swiss rejected the OJP real-time token "
                        "(HTTP %s); station boards continue without real-time data "
                        "until a valid token is configured",
                        err.status,
                    )
                    self._ojp_auth_failed = True
                    # The board itself keeps working, so the entry is not
                    # failed; only the token is asked for again.
                    _async_start_token_reauth(self.hass, self._entry, token)
            except Exception:  # noqa: BLE001 - enrichment must never break the board
                _LOGGER.debug("OJP real-time enrichment failed", exc_info=True)
            else:
                if self._ojp_auth_failed:
                    _LOGGER.info("opentransportdata.swiss accepts the OJP real-time token again")
                    self._ojp_auth_failed = False
                # Accepted: should it be rejected later, ask again.
                self.hass.data.pop(_REAUTH_ASKED, None)
        else:
            # Token removed: a token entered later starts with a clean slate.
            self._ojp_auth_failed = False
        if wanted:
            self._filter_directions(result, wanted, limit)

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
            update_interval=timedelta(seconds=CONNECTION_UPDATE_INTERVAL_SECONDS),
        )
        self._entry = entry
        self.issues = IssueReporter(hass, entry.entry_id)

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
            result = await async_fetch_connections(
                self.hass,
                data[CONF_FROM_ID],
                data[CONF_TO_ID],
                limit,
                self._entry.options.get(CONF_LINE_LABEL, DEFAULT_LINE_LABEL),
            )
        except Exception as err:
            _apply_rate_limit_backoff(self, err, CONNECTION_UPDATE_INTERVAL_SECONDS)
            self.issues.failure("unreachable", {"host": "transport.opendata.ch"})
            raise UpdateFailed(f"transport.opendata.ch unreachable: {err}") from err
        self.issues.clear("unreachable")
        self.update_interval = timedelta(seconds=CONNECTION_UPDATE_INTERVAL_SECONDS)
        return result
