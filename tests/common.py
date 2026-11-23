"""Fake answers of transport.opendata.ch, OpenStreetMap Nominatim and
opentransportdata.swiss, and the config entries the tests set up.

`FakeApi` answers every request of the shared client session from memory,
at a fixed moment (`NOW`), so a test sees the same timetable every time."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.swiss_transport.const import (
    API_BASE,
    CONF_ENTRY_TYPE,
    CONF_FROM_ID,
    CONF_FROM_NAME,
    CONF_LIMIT,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    CONF_TO_ID,
    CONF_TO_NAME,
    DOMAIN,
    ENTRY_TYPE_CONNECTION,
    ENTRY_TYPE_STATION,
    OJP_ENDPOINT,
    UPDATE_INTERVAL_SECONDS,
)
from custom_components.swiss_transport.coordinator import NOMINATIM_URL

# A Monday morning in November, 07:00 local time in Switzerland.
NOW = datetime(2026, 11, 9, 6, 0, tzinfo=UTC)
SWISS = ZoneInfo("Europe/Zurich")

BOARD_URL = f"{API_BASE}/stationboard"
CONNECTIONS_URL = f"{API_BASE}/connections"
LOCATIONS_URL = f"{API_BASE}/locations"

BOARD_ENTITY = "sensor.swiss_transport_bern_0001"
ROUTE_ENTITY = "sensor.swiss_transport_bern_thun_0001"

BERN = {"id": "8507000", "name": "Bern", "coordinate": {"x": 46.949, "y": 7.439}}
THUN = {"id": "8507100", "name": "Thun", "coordinate": {"x": 46.755, "y": 7.630}}
ADDRESS = {"address": {"road": "Bahnhofplatz", "postcode": "3011", "city": "Bern"}}


def ts(minutes: float) -> int:
    """Unix time of the moment `minutes` after NOW."""
    return int(NOW.timestamp() + minutes * 60)


def state_time(minutes: float) -> str:
    """How a timestamp sensor shows the moment `minutes` after NOW."""
    return (NOW + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def local_time(minutes: float) -> str:
    """The moment as transport.opendata.ch writes it (Swiss local time)."""
    return (NOW + timedelta(minutes=minutes)).astimezone(SWISS).strftime("%Y-%m-%dT%H:%M:%S%z")


def departure(
    minutes: float,
    category: str = "IC",
    number: str = "8",
    to: str = "Zürich HB",
    *,
    delay: int | None = 0,
    platform: str | None = "7",
    new_platform: str | None = None,
    cancelled: bool | None = None,
    capacity: tuple[int | None, int | None] | None = None,
) -> dict[str, Any]:
    """One row of a /stationboard answer; `capacity` is (1st, 2nd class)."""
    stop: dict[str, Any] = {
        "departure": local_time(minutes),
        "departureTimestamp": ts(minutes),
        "delay": delay,
        "platform": platform,
    }
    if new_platform:
        stop["prognosis"] = {"platform": new_platform}
    row: dict[str, Any] = {"category": category, "number": number, "to": to, "operator": "SBB", "stop": stop}
    if cancelled is not None:
        row["cancelled"] = cancelled
    if capacity is not None:
        row["capacity1st"], row["capacity2nd"] = capacity
    return row


def board(rows: list[dict] | None = None, *, name: str | None = "Bern", coordinate: bool = True) -> dict[str, Any]:
    """A /stationboard answer for Bern."""
    if rows is None:
        rows = [departure(4, "S", "9", "Thun", platform="3"), departure(12)]
    station: dict[str, Any] = {"id": BERN["id"], "name": name}
    if coordinate:
        station["coordinate"] = dict(BERN["coordinate"])
    return {"station": station, "stationboard": rows}


def connection(minutes: float, *, duration: int = 20, delay: int | None = 0, arrival: bool = True) -> dict[str, Any]:
    """One direct connection Bern -> Thun of a /connections answer."""
    to: dict[str, Any] = {"platform": "2"}
    if arrival:
        to.update({"arrival": local_time(minutes + duration), "arrivalTimestamp": ts(minutes + duration)})
    return {
        "from": {"departure": local_time(minutes), "departureTimestamp": ts(minutes), "platform": "4", "delay": delay},
        "to": to,
        "duration": f"00d00:{duration:02d}:00",
        "transfers": 0,
        "products": ["IC 6"],
        "sections": [
            {
                "journey": {"category": "IC", "number": "6", "to": "Brig", "operator": "SBB"},
                "departure": {"station": {"name": "Bern"}, "platform": "4"},
                "arrival": {"station": {"name": "Thun"}, "platform": "2"},
            }
        ],
    }


def connections(rows: list[dict] | None = None, *, named: bool = True) -> dict[str, Any]:
    """A /connections answer for Bern -> Thun."""
    if rows is None:
        rows = [connection(6), connection(36)]
    answer: dict[str, Any] = {"connections": rows}
    if named:
        answer.update({"from": {"name": "Bern"}, "to": {"name": "Thun"}})
    return answer


def _ojp_time(minutes: float) -> str:
    return (NOW + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def ojp_event(
    minutes: float | None,
    destination: str,
    *,
    estimated: float | None = None,
    cancelled: bool = False,
    planned_quay: str | None = None,
    estimated_quay: str | None = None,
    occupancy: tuple[str, ...] = (),
    line: str | None = None,
    direction: str | None = None,
) -> str:
    """One StopEventResult of an OJP answer; `estimated` is in minutes after NOW."""
    times = f"<TimetabledTime>{_ojp_time(minutes)}</TimetabledTime>" if minutes is not None else ""
    if estimated is not None:
        times += f"<EstimatedTime>{_ojp_time(estimated)}</EstimatedTime>"
    quays = f"<PlannedQuay><Text>{planned_quay}</Text></PlannedQuay>" if planned_quay else ""
    if estimated_quay:
        quays += f"<EstimatedQuay><Text>{estimated_quay}</Text></EstimatedQuay>"
    levels = "".join(
        f"<ExpectedDepartureOccupancy><OccupancyLevel>{level}</OccupancyLevel></ExpectedDepartureOccupancy>"
        for level in occupancy
    )
    return (
        "<StopEventResult><StopEvent><ThisCall><CallAtStop>"
        f"{quays}<ServiceDeparture>{times}</ServiceDeparture>{levels}"
        "</CallAtStop></ThisCall>"
        "<Service>"
        + (f"<siri:DirectionRef>{direction}</siri:DirectionRef>" if direction else "")
        + (f"<PublishedServiceName><Text>{line}</Text></PublishedServiceName>" if line else "")
        + f"<DestinationText><Text>{destination}</Text></DestinationText>"
        f"<Cancelled>{'true' if cancelled else 'false'}</Cancelled></Service>"
        "</StopEvent></StopEventResult>"
    )


def ojp_situation(text: str | None) -> str:
    """One disruption of an OJP answer; without a text when `text` is None."""
    if text is None:
        return "<PtSituation><siri:Priority>3</siri:Priority></PtSituation>"
    return (
        "<PtSituation><siri:PassengerInformationAction><siri:TextualContent><siri:SummaryContent>"
        f"<siri:SummaryText>{text}</siri:SummaryText>"
        "</siri:SummaryContent></siri:TextualContent></siri:PassengerInformationAction></PtSituation>"
    )


def ojp_xml(events: list[str] | None = None, situations: list[str] | None = None) -> str:
    """An OJP StopEventResponse."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<OJP xmlns="http://www.vdv.de/ojp" xmlns:siri="http://www.siri.org.uk/siri" version="2.0">'
        "<OJPResponse><siri:ServiceDelivery><OJPStopEventDelivery>"
        f"{''.join(situations or [])}{''.join(events or [])}"
        "</OJPStopEventDelivery></siri:ServiceDelivery></OJPResponse></OJP>"
    )


class FakeApi:
    """The three services the integration talks to, answered from memory.

    The attributes hold the next answers and can be changed at any time.
    `fail[route]` makes a route answer with an HTTP status (an int) or raise
    (an exception); the routes are "board", "connections", "locations",
    "geocode", "ojp" and "ojp_later" (only the requests for a later time)."""

    def __init__(self, mocker: AiohttpClientMocker) -> None:
        self.mocker = mocker
        self.board: dict[str, Any] = board()
        self.connections: dict[str, Any] = connections()
        self.stations: dict[str, list[dict]] = {"bern": [BERN], "thun": [THUN]}
        self.address: dict[str, Any] = ADDRESS
        self.ojp: str = ojp_xml()
        # the answer to a request for a later time; None = the same as for now
        self.ojp_later: str | None = None
        self.fail: dict[str, int | Exception] = {}
        mocker.get(BOARD_URL, side_effect=self._board)
        mocker.get(CONNECTIONS_URL, side_effect=self._connections)
        mocker.get(LOCATIONS_URL, side_effect=self._locations)
        mocker.get(NOMINATIM_URL, side_effect=self._geocode)
        mocker.post(OJP_ENDPOINT, side_effect=self._ojp)

    def _answer(self, route: str, method: str, url, **body: Any) -> AiohttpClientMockResponse:
        failure = self.fail.get(route)
        if isinstance(failure, Exception):
            raise failure
        if failure:
            return AiohttpClientMockResponse(method, url, status=failure)
        return AiohttpClientMockResponse(method, url, **body)

    async def _board(self, method, url, data) -> AiohttpClientMockResponse:
        return self._answer("board", method, url, json=self.board)

    async def _connections(self, method, url, data) -> AiohttpClientMockResponse:
        return self._answer("connections", method, url, json=self.connections)

    async def _locations(self, method, url, data) -> AiohttpClientMockResponse:
        found = self.stations.get(url.query["query"].lower(), [])
        return self._answer("locations", method, url, json={"stations": found})

    async def _geocode(self, method, url, data) -> AiohttpClientMockResponse:
        return self._answer("geocode", method, url, json=self.address)

    async def _ojp(self, method, url, data) -> AiohttpClientMockResponse:
        later = b"<DepArrTime>" in data
        route = "ojp_later" if later and "ojp_later" in self.fail else "ojp"
        return self._answer(route, method, url, text=self.ojp_later if later and self.ojp_later is not None else self.ojp)

    def requests(self, url: str) -> list[tuple]:
        """The requests sent to one address so far, as (method, url, body, headers)."""
        return [call for call in self.mocker.mock_calls if str(call[1].with_query(None)) == url]


def add_board(
    hass: HomeAssistant,
    *,
    entry_id: str = "board0001",
    station: dict[str, Any] = BERN,
    options: dict[str, Any] | None = None,
    **data: Any,
) -> MockConfigEntry:
    """A departure board entry (Bern unless told otherwise), not yet set up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=entry_id,
        unique_id=f"station_{station['id']}",
        title=f"Departures {station['name']}",
        data={
            CONF_ENTRY_TYPE: ENTRY_TYPE_STATION,
            CONF_STATION_ID: station["id"],
            CONF_STATION_NAME: station["name"],
            CONF_LIMIT: 8,
            **data,
        },
        options=options or {},
    )
    entry.add_to_hass(hass)
    return entry


def add_connection(
    hass: HomeAssistant, *, entry_id: str = "route0001", options: dict[str, Any] | None = None
) -> MockConfigEntry:
    """A saved connection Bern -> Thun, not yet set up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=entry_id,
        unique_id=f"connection_{BERN['id']}_{THUN['id']}",
        title="Bern → Thun",
        data={
            CONF_ENTRY_TYPE: ENTRY_TYPE_CONNECTION,
            CONF_FROM_ID: BERN["id"],
            CONF_FROM_NAME: "Bern",
            CONF_TO_ID: THUN["id"],
            CONF_TO_NAME: "Thun",
            CONF_LIMIT: 6,
        },
        options=options or {},
    )
    entry.add_to_hass(hass)
    return entry


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    """Set an entry up and wait until its entities are there."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def poll(hass: HomeAssistant, freezer, seconds: int = UPDATE_INTERVAL_SECONDS + 1) -> None:
    """Let time pass so that a scheduled refresh runs."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
