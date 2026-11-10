"""Pure parsing helpers of the coordinator: the transport.opendata.ch
stationboard and connection answers, the OJP real-time overlay and the
rate-limit backoff."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from custom_components.swiss_transport.coordinator import (
    _apply_ojp,
    _apply_rate_limit_backoff,
    _duration_to_minutes,
    _ojp_iso_to_ts,
    _parse_board,
    _parse_connection,
    _parse_departure,
    _parse_ojp_stationboard,
)

BOARD_ENTRY = {
    "category": "IC", "number": "8", "to": "Zürich HB", "operator": "SBB",
    "stop": {"departure": "2026-11-09T07:12:00+0100", "departureTimestamp": 1794207120, "delay": 2, "platform": "7",
             "prognosis": {"platform": "9"}},
}


def test_train_departure_uses_the_category_as_line():
    dep = _parse_departure(BOARD_ENTRY)
    assert dep["line"] == "IC"
    assert dep["to"] == "Zürich HB"
    assert dep["departure_ts"] == 1794207120
    assert dep["delay"] == 2
    assert dep["platform"] == "7"
    assert dep["platform_changed"] is True


def test_bus_departure_uses_the_number_as_line():
    entry = {"category": "B", "number": "31", "to": "Bahnhof", "stop": {"departureTimestamp": 1794207120, "platform": None}}
    dep = _parse_departure(entry)
    assert dep["line"] == "31"
    assert dep["delay"] is None
    assert dep["platform_changed"] is False


def test_regional_train_with_letter_number_combines_both():
    entry = {"category": "S", "number": "S9", "stop": {"departureTimestamp": 1}}
    assert _parse_departure(entry)["line"] == "SS9"  # category + non-numeric number, as the API delivers it


def test_departure_without_timestamp_is_dropped():
    assert _parse_departure({"category": "IC", "stop": {}}) is None


def test_board_sorts_and_skips_broken_rows():
    data = {"stationboard": [
        {"category": "IR", "number": "16", "stop": {"departureTimestamp": 200}},
        {"category": "S", "stop": None},  # malformed, must not kill the refresh
        {"category": "IC", "number": "1", "stop": {"departureTimestamp": 100}},
    ]}
    deps = _parse_board(data)
    assert [d["departure_ts"] for d in deps] == [100, 200]


def test_connection_legs_and_changes():
    con = {
        "from": {"departure": "2026-11-09T07:00:00+0100", "departureTimestamp": 1000, "platform": "4", "delay": 0},
        "to": {"arrival": "2026-11-09T08:30:00+0100", "arrivalTimestamp": 6400, "platform": "2"},
        "duration": "00d01:30:00", "transfers": 1, "products": ["IC 8", "S 9"],
        "sections": [
            {"journey": {"category": "IC", "number": "8", "to": "Zürich HB"},
             "departure": {"station": {"name": "Luzern"}, "platform": "4"}, "arrival": {"station": {"name": "Zürich HB"}, "platform": "33"}},
            {"journey": None, "walk": {"duration": 300}},
            {"journey": {"category": "S", "number": "9", "to": "Uster"},
             "departure": {"station": {"name": "Zürich HB"}, "platform": "43"}, "arrival": {"station": {"name": "Uster"}, "platform": "2"}},
        ],
    }
    parsed = _parse_connection(con)
    assert parsed["duration_min"] == 90
    assert parsed["arrival_ts"] == 6400
    assert [leg["line"] for leg in parsed["legs"]] == ["IC", "S"]
    assert parsed["changes"] == [{"station": "Zürich HB", "arr_platform": "33", "dep_platform": "43"}]


def test_duration_parser():
    assert _duration_to_minutes("00d00:27:00") == 27
    assert _duration_to_minutes("01d02:05:00") == 1565
    assert _duration_to_minutes(None) is None


def test_ojp_time_parser():
    from datetime import datetime, timezone

    assert _ojp_iso_to_ts("2026-07-19T21:32:00Z") == int(datetime(2026, 7, 19, 21, 32, tzinfo=timezone.utc).timestamp())
    assert _ojp_iso_to_ts(None) is None
    assert _ojp_iso_to_ts("garbage") is None


OJP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OJP xmlns="http://www.vdv.de/ojp" xmlns:siri="http://www.siri.org.uk/siri" version="2.0">
 <OJPResponse><siri:ServiceDelivery><OJPStopEventDelivery>
  <PtSituation><siri:Summary>x</siri:Summary>
    <siri:PassengerInformationAction><siri:TextualContent><siri:SummaryContent>
      <siri:SummaryText>Luzern: Gleisänderung wegen Bauarbeiten</siri:SummaryText>
    </siri:SummaryContent></siri:TextualContent></siri:PassengerInformationAction>
  </PtSituation>
  <StopEventResult><StopEvent>
   <ThisCall><CallAtStop>
     <PlannedQuay><Text>7</Text></PlannedQuay><EstimatedQuay><Text>9</Text></EstimatedQuay>
     <ServiceDeparture><TimetabledTime>2026-11-09T06:12:00Z</TimetabledTime><EstimatedTime>2026-11-09T06:15:30Z</EstimatedTime></ServiceDeparture>
     <ExpectedDepartureOccupancy><OccupancyLevel>fewSeatsAvailable</OccupancyLevel></ExpectedDepartureOccupancy>
   </CallAtStop></ThisCall>
   <Service><DestinationText><Text>Zürich HB</Text></DestinationText><Cancelled>false</Cancelled></Service>
  </StopEvent></StopEventResult>
  <StopEventResult><StopEvent>
   <ThisCall><CallAtStop>
     <ServiceDeparture><TimetabledTime>2026-11-09T06:12:00Z</TimetabledTime></ServiceDeparture>
   </CallAtStop></ThisCall>
   <Service><DestinationText><Text>Basel SBB</Text></DestinationText><Cancelled>true</Cancelled></Service>
  </StopEvent></StopEventResult>
 </OJPStopEventDelivery></siri:ServiceDelivery></OJPResponse>
</OJP>"""


def test_ojp_stationboard_parser():
    ojp = _parse_ojp_stationboard(OJP_XML)
    assert ojp["alerts"] == ["Luzern: Gleisänderung wegen Bauarbeiten"]
    planned = _ojp_iso_to_ts("2026-11-09T06:12:00Z")
    events = ojp["events"][planned]
    assert len(events) == 2
    zurich = next(e for e in events if e["destination"] == "Zürich HB")
    assert zurich["cancelled"] is False
    assert zurich["occupancy"] == 2
    assert zurich["estimated_quay"] == "9"
    basel = next(e for e in events if e["destination"] == "Basel SBB")
    assert basel["cancelled"] is True


def test_ojp_overlay_matches_by_time_and_destination():
    planned = _ojp_iso_to_ts("2026-11-09T06:12:00Z")
    board = {"departures": [
        {"departure_ts": planned, "to": "Zürich HB", "delay": 0, "platform": "7", "platform_changed": False},
        {"departure_ts": planned, "to": "Basel SBB", "delay": 0, "platform": "3", "platform_changed": False},
        {"departure_ts": planned + 600, "to": "Bern", "delay": 0, "platform": "1", "platform_changed": False},
    ]}
    _apply_ojp(board, _parse_ojp_stationboard(OJP_XML))
    zurich, basel, bern = board["departures"]
    assert zurich["delay"] == 4  # 3.5 minutes estimated, rounded
    assert zurich["platform"] == "9" and zurich["platform_changed"] is True
    assert zurich["occupancy"] == 2 and zurich["cancelled"] is False
    assert basel["cancelled"] is True and basel["platform"] == "3"
    assert "cancelled" not in bern  # no real-time row for it
    assert board["realtime"] is True
    assert board["alerts"] == ["Luzern: Gleisänderung wegen Bauarbeiten"]


def test_rate_limit_backoff_only_on_429():
    coordinator = SimpleNamespace(update_interval=timedelta(seconds=90))
    _apply_rate_limit_backoff(coordinator, SimpleNamespace(status=500), 90)
    assert coordinator.update_interval == timedelta(seconds=90)
    _apply_rate_limit_backoff(coordinator, SimpleNamespace(status=429), 90)
    assert coordinator.update_interval == timedelta(seconds=1800)
    _apply_rate_limit_backoff(coordinator, RuntimeError("other"), 90)
    assert coordinator.update_interval == timedelta(seconds=90)
