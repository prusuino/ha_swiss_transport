"""What a refresh makes of the answers of the three services: the station
address, broken rows, cancelled journeys and occupancy, the real-time overlay
and its token, the rate-limit pause and the repair issue."""
from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.swiss_transport.const import CONF_LIMIT, DOMAIN, OJP_ENDPOINT
from custom_components.swiss_transport.coordinator import NOMINATIM_URL

from .common import (
    BOARD_ENTITY,
    BOARD_URL,
    CONNECTIONS_URL,
    ROUTE_ENTITY,
    FakeApi,
    add_board,
    add_connection,
    board,
    connection,
    connections,
    departure,
    ojp_event,
    ojp_situation,
    ojp_xml,
    poll,
    setup,
    state_time,
    ts,
)

TOKEN = {"ojp_token": "made-up-token"}


def _attrs(hass: HomeAssistant, entity_id: str = BOARD_ENTITY):
    return hass.states.get(entity_id).attributes


def _reauth_flows(hass: HomeAssistant) -> list:
    return hass.config_entries.flow.async_progress_by_handler(DOMAIN, match_context={"source": SOURCE_REAUTH})


def _warnings(caplog, text: str) -> int:
    return sum(1 for record in caplog.records if record.levelno == logging.WARNING and text in record.getMessage())


# ------------------------------------------------------------------ address


@pytest.mark.parametrize(
    ("answer", "address"),
    [
        ({"address": {"pedestrian": "Bahnhofplatz", "town": "Thun"}}, "Bahnhofplatz, Thun"),
        ({"address": {"neighbourhood": "Altstadt", "municipality": "Bern"}}, "Altstadt, Bern"),
        ({"address": {"postcode": "3011", "village": "Bern"}}, "3011 Bern"),
        ({"address": {"road": "Bahnhofplatz"}}, "Bahnhofplatz"),
        ({}, None),
    ],
)
async def test_address_is_built_from_what_the_geocoder_knows(hass: HomeAssistant, api: FakeApi, answer, address) -> None:
    api.address = answer
    await setup(hass, add_board(hass))
    assert _attrs(hass)["address"] == address


async def test_geocoder_is_asked_politely_and_only_until_it_answers(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    api.fail["geocode"] = 500
    await setup(hass, add_board(hass))
    assert hass.states.get(BOARD_ENTITY).state == state_time(4)
    assert _attrs(hass)["address"] is None

    api.fail.clear()
    await poll(hass, freezer)
    assert _attrs(hass)["address"] == "Bahnhofplatz, 3011 Bern"

    await poll(hass, freezer)
    requests = api.requests(NOMINATIM_URL)
    assert len(requests) == 2
    assert (requests[0][1].query["lat"], requests[0][1].query["lon"]) == ("46.949", "7.439")
    assert "ha-swiss-transport" in requests[0][3]["User-Agent"]


async def test_station_without_coordinates_is_not_geocoded(hass: HomeAssistant, api: FakeApi) -> None:
    api.board = board(coordinate=False)
    await setup(hass, add_board(hass))
    assert api.requests(NOMINATIM_URL) == []
    assert _attrs(hass)["address"] is None
    assert _attrs(hass)["latitude"] is None


# --------------------------------------------------------------- the board


async def test_broken_rows_are_left_out_of_the_board(hass: HomeAssistant, api: FakeApi) -> None:
    no_time = departure(2)
    del no_time["stop"]["departureTimestamp"]
    api.board = board([departure(9), {**departure(1), "category": 5}, no_time, departure(4, "S", "9", "Thun")])
    await setup(hass, add_board(hass))
    assert [dep["departure_ts"] for dep in _attrs(hass)["departures"]] == [ts(4), ts(9)]


async def test_station_id_of_the_entry_is_kept_when_the_answer_names_none(hass: HomeAssistant, api: FakeApi) -> None:
    api.board = {"stationboard": [departure(4)]}
    await setup(hass, add_board(hass))
    assert _attrs(hass)["station_id"] == "8507000"
    assert _attrs(hass)["station_name"] is None


async def test_board_is_asked_for_once_with_cancelled_journeys(hass: HomeAssistant, api: FakeApi) -> None:
    # A first departure far ahead (a small stop late at night) is no reason
    # for a second request.
    api.board = board([departure(70), departure(80)])
    await setup(hass, add_board(hass))
    (request,) = api.requests(BOARD_URL)
    assert request[1].query["showCancelled"] == "1"
    assert "datetime" not in request[1].query
    assert [dep["departure_ts"] for dep in _attrs(hass)["departures"]] == [ts(70), ts(80)]


async def test_cancelled_journeys_and_occupancy_need_no_token(hass: HomeAssistant, api: FakeApi) -> None:
    api.board = board(
        [
            departure(4, "S", "9", "Thun", cancelled=False, capacity=(1, 2)),
            departure(12, "IC", "1", "Genève-Aéroport", cancelled=True, capacity=(3, 1)),
            departure(20, "IR", "15", "Luzern", capacity=(None, None)),
            departure(25, "RE", "1", "Biel/Bienne", cancelled=False, capacity=(0, 7)),
            departure(30, "B", "10", "Köniz", platform=None),
        ]
    )
    await setup(hass, add_board(hass))

    attrs = _attrs(hass)
    assert attrs["realtime"] is False
    assert api.requests(OJP_ENDPOINT) == []
    thun, geneva, luzern, biel, bus = attrs["departures"]
    assert (thun["cancelled"], thun["occupancy"]) == (False, 2)
    assert (geneva["cancelled"], geneva["occupancy"]) == (True, 3)
    # No forecast, a value outside the scale, a row without the fields.
    assert luzern["cancelled"] is False and "occupancy" not in luzern
    assert "occupancy" not in biel
    assert bus["cancelled"] is False and "occupancy" not in bus


# ---------------------------------------------------------------- real time


async def test_realtime_answer_is_laid_over_the_board(hass: HomeAssistant, api: FakeApi) -> None:
    api.board = board(
        [
            departure(4, "S", "9", "Thun", platform="3"),
            departure(12, "IC", "8", "Zürich HB", delay=1, platform="7"),
            departure(12, "IC", "6", "Basel SBB", platform="5"),
            departure(20, "IR", "15", "Genève-Aéroport", platform="8"),
            departure(30, "RE", "1", "Luzern", delay=2),
        ]
    )
    api.ojp = ojp_xml(
        [
            ojp_event(4, "Thun", estimated=7, planned_quay="3", estimated_quay="5", occupancy=("fewSeatsAvailable", "full", "unheard of")),
            ojp_event(12, "Basel SBB", cancelled=True),
            ojp_event(12, "Zürich HB", estimated=12, planned_quay="7", estimated_quay="7", occupancy=("many seats available",)),
            ojp_event(20, "Lausanne"),
            ojp_event(20, "Fribourg/Freiburg", cancelled=True),
            ojp_event(None, "Nowhere", cancelled=True),
        ],
        [
            ojp_situation("Bern: track works until Friday"),
            ojp_situation(None),
            ojp_situation("  Bern: track works until Friday "),
            ojp_situation("   "),
            ojp_situation("Lift on platform 7 out of order"),
        ],
    )
    await setup(hass, add_board(hass, options=TOKEN))

    method, _url, body, headers = api.requests(OJP_ENDPOINT)[0]
    assert method.lower() == "post"
    assert headers["Authorization"] == "Bearer made-up-token"
    assert headers["Content-Type"] == "application/xml"
    request = body.decode("utf-8")
    assert "<siri:StopPointRef>8507000</siri:StopPointRef>" in request
    assert "<NumberOfResults>8</NumberOfResults>" in request
    assert "<siri:RequestTimestamp>2026-11-09T06:00:00Z</siri:RequestTimestamp>" in request

    attrs = _attrs(hass)
    assert attrs["realtime"] is True
    assert attrs["alerts"] == ["Bern: track works until Friday", "Lift on platform 7 out of order"]
    assert attrs["attribution"].endswith("Real-time: opentransportdata.swiss (OJP)")
    thun, zurich, basel, geneva, luzern = attrs["departures"]
    assert (thun["delay"], thun["platform"], thun["platform_changed"]) == (3, "5", True)
    assert (thun["occupancy"], thun["cancelled"]) == (3, False)
    assert (zurich["delay"], zurich["platform"], zurich["platform_changed"]) == (0, "7", False)
    assert (zurich["occupancy"], zurich["cancelled"]) == (1, False)
    assert basel["cancelled"] is True
    assert "occupancy" not in basel
    # No real-time row names this destination: the first one of the minute counts.
    assert geneva["cancelled"] is False
    # No real-time row at all: the timetable values stay.
    assert luzern["cancelled"] is False
    assert luzern["delay"] == 2


async def test_realtime_overlay_keeps_what_the_board_already_knows(hass: HomeAssistant, api: FakeApi) -> None:
    api.board = board(
        [
            departure(4, "S", "9", "Thun", platform="3", cancelled=True, capacity=(1, 2)),
            departure(12, "IC", "8", "Zürich HB", capacity=(1, 1)),
        ]
    )
    siri_occupancy = (
        "<siri:ExpectedDepartureOccupancy><siri:FareClass>secondClass</siri:FareClass>"
        "<siri:OccupancyLevel>standingRoomOnly</siri:OccupancyLevel></siri:ExpectedDepartureOccupancy>"
    )
    api.ojp = ojp_xml(
        [
            ojp_event(4, "Thun"),
            ojp_event(12, "Zürich HB").replace("</CallAtStop>", f"{siri_occupancy}</CallAtStop>"),
        ]
    )
    await setup(hass, add_board(hass, options=TOKEN))

    thun, zurich = _attrs(hass)["departures"]
    # Cancelled on the board stays cancelled, its occupancy forecast stays too.
    assert (thun["cancelled"], thun["occupancy"]) == (True, 2)
    # The occupancy elements of OJP 2.0 are SIRI elements; they win over the board.
    assert (zurich["cancelled"], zurich["occupancy"]) == (False, 3)


async def test_token_entered_on_one_entry_serves_every_board(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    await setup(hass, add_board(hass))
    assert api.requests(OJP_ENDPOINT) == []
    assert _attrs(hass)["realtime"] is False

    await setup(hass, add_connection(hass, options=TOKEN))
    await poll(hass, freezer)
    assert api.requests(OJP_ENDPOINT)[0][3]["Authorization"] == "Bearer made-up-token"
    assert _attrs(hass)["realtime"] is True


async def test_rejected_token_is_reported_once_and_the_board_goes_on(hass: HomeAssistant, api: FakeApi, freezer, caplog) -> None:
    api.fail["ojp"] = 401
    await setup(hass, add_board(hass, options=TOKEN))
    await poll(hass, freezer)
    assert hass.states.get(BOARD_ENTITY).state == state_time(4)
    assert _attrs(hass)["realtime"] is False
    assert _warnings(caplog, "rejected the OJP real-time token (HTTP 401)") == 1
    assert [flow["step_id"] for flow in _reauth_flows(hass)] == ["reauth_confirm"]

    api.fail.clear()
    with caplog.at_level(logging.INFO):
        await poll(hass, freezer)
    assert _attrs(hass)["realtime"] is True
    assert "accepts the OJP real-time token again" in caplog.text


async def test_rejection_is_reported_again_after_the_token_was_taken_out(hass: HomeAssistant, api: FakeApi, caplog) -> None:
    api.fail["ojp"] = 403
    entry = await setup(hass, add_board(hass, options=TOKEN))
    assert _warnings(caplog, "rejected the OJP real-time token (HTTP 403)") == 1

    hass.config_entries.async_update_entry(entry, options={})
    await hass.async_block_till_done()
    assert len(api.requests(OJP_ENDPOINT)) == 1

    hass.config_entries.async_update_entry(entry, options={"ojp_token": "another-made-up-token"})
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert _warnings(caplog, "rejected the OJP real-time token (HTTP 403)") == 2
    assert _attrs(hass)["realtime"] is False


async def test_realtime_outage_leaves_the_timetable_board(hass: HomeAssistant, api: FakeApi, caplog) -> None:
    api.fail["ojp"] = 500
    await setup(hass, add_board(hass, options=TOKEN))
    assert hass.states.get(BOARD_ENTITY).state == state_time(4)
    assert _attrs(hass)["realtime"] is False
    assert _attrs(hass)["attribution"] == "Data: transport.opendata.ch (opentransportdata.swiss). Address: © OpenStreetMap contributors"
    assert _reauth_flows(hass) == []
    assert _warnings(caplog, "OJP") == 0


# ------------------------------------------------- failures and rate limit


async def test_board_pauses_after_http_429_and_resumes(hass: HomeAssistant, api: FakeApi, freezer, caplog) -> None:
    entry = await setup(hass, add_board(hass))
    api.fail["board"] = 429
    await poll(hass, freezer)
    assert hass.states.get(BOARD_ENTITY).state == STATE_UNAVAILABLE
    assert entry.runtime_data.update_interval == timedelta(minutes=30)
    assert len(api.requests(BOARD_URL)) == 2

    await poll(hass, freezer)
    assert len(api.requests(BOARD_URL)) == 2  # the normal cadence is suspended

    await poll(hass, freezer, 30 * 60)
    assert len(api.requests(BOARD_URL)) == 3
    assert _warnings(caplog, "rate limit hit (HTTP 429)") == 1  # said once, not on every probe

    api.fail.clear()
    await poll(hass, freezer, 30 * 60)
    assert hass.states.get(BOARD_ENTITY).state != STATE_UNAVAILABLE
    assert entry.runtime_data.update_interval == timedelta(seconds=90)


async def test_other_failures_keep_the_normal_cadence(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    entry = await setup(hass, add_board(hass))
    api.fail["board"] = TimeoutError()
    await poll(hass, freezer)
    assert hass.states.get(BOARD_ENTITY).state == STATE_UNAVAILABLE
    assert entry.runtime_data.update_interval == timedelta(seconds=90)
    await poll(hass, freezer)
    assert len(api.requests(BOARD_URL)) == 3


async def test_repair_issue_after_three_failed_refreshes_goes_with_the_next_good_one(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    entry = await setup(hass, add_board(hass))
    issues = ir.async_get(hass)
    issue_id = f"unreachable_{entry.entry_id}"
    api.fail["board"] = 502
    await poll(hass, freezer)
    await poll(hass, freezer)
    assert issues.async_get_issue(DOMAIN, issue_id) is None
    await poll(hass, freezer)
    issue = issues.async_get_issue(DOMAIN, issue_id)
    assert issue.translation_key == "unreachable"
    assert issue.translation_placeholders == {"host": "transport.opendata.ch"}
    assert issue.severity is ir.IssueSeverity.WARNING

    api.fail.clear()
    await poll(hass, freezer)
    assert issues.async_get_issue(DOMAIN, issue_id) is None
    assert hass.states.get(BOARD_ENTITY).state == state_time(4)


# -------------------------------------------------------------- connections


async def test_broken_connections_are_left_out(hass: HomeAssistant, api: FakeApi) -> None:
    no_time = connection(3)
    del no_time["from"]["departureTimestamp"]
    api.connections = connections([connection(36), {**connection(2), "sections": [None]}, no_time, connection(6)])
    await setup(hass, add_connection(hass))
    assert [con["departure_ts"] for con in _attrs(hass, ROUTE_ENTITY)["connections"]] == [ts(6), ts(36)]


async def test_connections_pause_after_http_429_and_resume(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    entry = await setup(hass, add_connection(hass))
    assert entry.runtime_data.update_interval == timedelta(minutes=5)
    api.fail["connections"] = 429
    await poll(hass, freezer, 301)
    assert hass.states.get(ROUTE_ENTITY).state == STATE_UNAVAILABLE
    assert entry.runtime_data.update_interval == timedelta(minutes=30)

    api.fail.clear()
    await poll(hass, freezer, 30 * 60)
    assert hass.states.get(ROUTE_ENTITY).state == state_time(6)
    assert entry.runtime_data.update_interval == timedelta(minutes=5)
    assert len(api.requests(CONNECTIONS_URL)) == 3


async def test_connection_route_raises_and_clears_its_repair_issue(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    entry = await setup(hass, add_connection(hass))
    issues = ir.async_get(hass)
    api.fail["connections"] = 500
    for _ in range(3):
        await poll(hass, freezer, 301)
    assert issues.async_get_issue(DOMAIN, f"unreachable_{entry.entry_id}") is not None
    api.fail.clear()
    await poll(hass, freezer, 301)
    assert issues.async_get_issue(DOMAIN, f"unreachable_{entry.entry_id}") is None
