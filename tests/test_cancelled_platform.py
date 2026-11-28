"""A saved connection shows a platform change and, with a departure board of
its start station, a cancelled train; the two triggers for them; and the
commuter blueprint, whose text is rendered from states before and after a
refresh."""
from __future__ import annotations

from pathlib import Path

import yaml
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.template import Template
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

from .common import (
    BOARD_ENTITY,
    CONNECTIONS_URL,
    NOW,
    ROUTE_ENTITY,
    FakeApi,
    add_board,
    add_connection,
    board,
    connection,
    connections,
    departure,
    poll,
    setup,
    ts,
)

BLUEPRINT = Path(__file__).parent.parent / "blueprints" / "automation" / "commuter_alert.yaml"


def _moved(minutes: float, platform: str = "9", **kwargs) -> dict:
    """A connection whose train leaves from another platform than planned (4)."""
    con = connection(minutes, **kwargs)
    con["from"]["prognosis"] = {"platform": platform}
    con["sections"][0]["departure"]["prognosis"] = {"platform": platform}
    return con


def _next(hass: HomeAssistant, entity_id: str = ROUTE_ENTITY) -> dict:
    attrs = hass.states.get(entity_id).attributes
    return (attrs.get("connections") or attrs.get("departures"))[0]


async def _automation(hass: HomeAssistant, name: str, entity_id: str) -> list:
    calls = async_mock_service(hass, "test", "automation")
    config = {
        "alias": "Tell me",
        "trigger": {"trigger": f"swiss_transport.{name}", "target": {"entity_id": entity_id}},
        "action": {"action": "test.automation"},
    }
    assert await async_setup_component(hass, "automation", {"automation": config})
    await hass.async_block_till_done()
    assert hass.states.get("automation.tell_me").state == "on", "the automation was rejected"
    return calls


# ------------------------------------------------------------ platform change


async def test_a_connection_shows_the_platform_the_train_really_leaves_from(hass: HomeAssistant, api: FakeApi) -> None:
    api.connections = connections([_moved(6), connection(36)])
    await setup(hass, add_connection(hass))
    first, second = hass.states.get(ROUTE_ENTITY).attributes["connections"]
    assert (first["dep_platform"], first["dep_platform_planned"], first["platform_changed"]) == ("9", "4", True)
    assert first["legs"][0]["from_platform"] == "9" and first["legs"][0]["from_platform_changed"] is True
    assert (second["dep_platform"], second["dep_platform_planned"], second["platform_changed"]) == ("4", None, False)
    assert "from_platform_changed" not in second["legs"][0]


async def test_a_forecast_that_names_the_planned_platform_is_no_change(hass: HomeAssistant, api: FakeApi) -> None:
    api.connections = connections([_moved(6, platform="4")])
    await setup(hass, add_connection(hass))
    assert _next(hass)["platform_changed"] is False and _next(hass)["dep_platform"] == "4"


async def test_a_platform_change_at_the_transfer_is_marked(hass: HomeAssistant, api: FakeApi) -> None:
    con = connection(6)
    onward = {
        "journey": {"category": "S", "number": "1", "to": "Interlaken", "operator": "BLS"},
        "departure": {"station": {"name": "Thun"}, "platform": "1", "prognosis": {"platform": "3"}},
        "arrival": {"station": {"name": "Spiez"}, "platform": "2"},
    }
    con["sections"].append(onward)
    api.connections = connections([con])
    await setup(hass, add_connection(hass))
    assert _next(hass)["changes"] == [
        {"station": "Thun", "arr_platform": "2", "dep_platform": "3", "dep_platform_changed": True}
    ]
    assert _next(hass)["platform_changed"] is False  # the first train leaves as planned


# --------------------------------------------------------------- cancellation


async def test_without_a_board_a_connection_says_nothing_about_cancellation(hass: HomeAssistant, api: FakeApi) -> None:
    await setup(hass, add_connection(hass))
    assert "cancelled" not in _next(hass)


async def test_the_board_of_the_start_station_tells_that_the_train_is_cancelled(
    hass: HomeAssistant, api: FakeApi, freezer
) -> None:
    api.board = board([departure(6, "IC", "6", "Brig", cancelled=True), departure(36, "IC", "6", "Brig")])
    await setup(hass, add_board(hass))
    await setup(hass, add_connection(hass))
    first, second = hass.states.get(ROUTE_ENTITY).attributes["connections"]
    assert first["cancelled"] is True and second["cancelled"] is False

    # Another train at the same minute is not the one of the connection.
    api.board = board([departure(6, "IC", "8", "Zürich HB", cancelled=True), departure(6, "IC", "6", "Brig")])
    await poll(hass, freezer)
    assert _next(hass)["cancelled"] is False


async def test_a_cancellation_shows_with_the_next_board_refresh_and_costs_no_request(
    hass: HomeAssistant, api: FakeApi, freezer
) -> None:
    api.board = board([departure(6, "IC", "6", "Brig"), departure(36, "IC", "6", "Brig")])
    await setup(hass, add_board(hass))
    await setup(hass, add_connection(hass))
    assert _next(hass)["cancelled"] is False
    searches = len(api.requests(CONNECTIONS_URL))

    api.board = board([departure(6, "IC", "6", "Brig", cancelled=True), departure(36, "IC", "6", "Brig")])
    await poll(hass, freezer)  # 91 s: the board is read again, the route is not
    assert _next(hass)["cancelled"] is True
    assert len(api.requests(CONNECTIONS_URL)) == searches

    await poll(hass, freezer, 301)  # and the route's own search keeps the mark
    assert len(api.requests(CONNECTIONS_URL)) == searches + 1
    assert _next(hass)["cancelled"] is True


async def test_a_train_the_board_does_not_list_loses_its_mark(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    api.board = board([departure(6, "IC", "6", "Brig", cancelled=True)])
    await setup(hass, add_board(hass))
    await setup(hass, add_connection(hass))
    assert _next(hass)["cancelled"] is True
    api.board = board([departure(4, "S", "9", "Thun")])
    await poll(hass, freezer)
    assert "cancelled" not in _next(hass)


async def test_a_board_set_up_later_is_found_and_one_that_is_removed_is_let_go(
    hass: HomeAssistant, api: FakeApi, freezer
) -> None:
    await setup(hass, add_connection(hass))
    api.board = board([departure(6, "IC", "6", "Brig", cancelled=True)])
    entry = await setup(hass, add_board(hass))
    assert "cancelled" not in _next(hass)
    await poll(hass, freezer, 301)
    assert _next(hass)["cancelled"] is True

    assert await hass.config_entries.async_unload(entry.entry_id)
    await poll(hass, freezer, 301)
    assert "cancelled" not in _next(hass)


async def test_unloading_the_route_stops_following_the_board(hass: HomeAssistant, api: FakeApi) -> None:
    board_entry = await setup(hass, add_board(hass))
    route = await setup(hass, add_connection(hass))
    listeners = len(board_entry.runtime_data._listeners)
    assert await hass.config_entries.async_unload(route.entry_id)
    assert len(board_entry.runtime_data._listeners) == listeners - 1


# ------------------------------------------------------------------- triggers


async def test_cancelled_trigger_fires_for_every_cancelled_departure(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    await setup(hass, add_board(hass))
    calls = await _automation(hass, "departure_cancelled", BOARD_ENTITY)

    api.board = board([departure(4), departure(12, cancelled=True)])
    await poll(hass, freezer)
    assert len(calls) == 0  # only the next departure counts

    api.board = board([departure(4, cancelled=True), departure(12, cancelled=True)])
    await poll(hass, freezer)
    assert len(calls) == 1
    await poll(hass, freezer)
    assert len(calls) == 1  # the same train, still cancelled: quiet

    api.board = board([departure(12, cancelled=True), departure(20)])
    await poll(hass, freezer)
    assert len(calls) == 2  # the next one is cancelled as well: another train, another event

    api.board = board([departure(20), departure(30)])
    await poll(hass, freezer)
    assert len(calls) == 2


async def test_cancelled_trigger_watches_a_route_through_its_board(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    api.board = board([departure(6, "IC", "6", "Brig")])
    await setup(hass, add_board(hass))
    await setup(hass, add_connection(hass))
    calls = await _automation(hass, "departure_cancelled", ROUTE_ENTITY)
    api.board = board([departure(6, "IC", "6", "Brig", cancelled=True)])
    await poll(hass, freezer)
    assert len(calls) == 1


async def test_platform_trigger_fires_on_a_board_and_on_a_route(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    await setup(hass, add_board(hass))
    await setup(hass, add_connection(hass))
    calls = await _automation(hass, "platform_changed", [BOARD_ENTITY, ROUTE_ENTITY])

    api.board = board([departure(4, new_platform="8"), departure(12)])
    await poll(hass, freezer)
    assert len(calls) == 1

    api.connections = connections([_moved(6), connection(36)])
    await poll(hass, freezer, 301)
    assert len(calls) == 2
    await poll(hass, freezer, 301)
    assert len(calls) == 2  # nothing new


# ------------------------------------------------------------------ blueprint


class _Loader(yaml.SafeLoader):
    """Reads a blueprint: an !input is replaced by its name."""


_Loader.add_constructor("!input", lambda loader, node: f"<{node.value}>")

INPUTS = {
    "board_sensor": ROUTE_ENTITY,
    "train_from": "07:00:00",
    "train_until": "07:30:00",
    "lead_minutes": 60,
    "minimum_delay": 3,
    "all_clear": True,
}


def _route(*items: dict) -> State:
    return State(ROUTE_ENTITY, "2026-11-09T06:06:00+00:00", {"from_name": "Bern", "to_name": "Thun", "connections": list(items)})


def _con(minutes: float, **over) -> dict:
    """A connection as the sensor lists it; 07:06 local time for 6 minutes after NOW."""
    return {"departure_ts": ts(minutes), "products": ["IC 6"], "delay": 0, "dep_platform": "4",
            "dep_platform_planned": None, "platform_changed": False, **over}


def _message(hass: HomeAssistant, old: State | None, new: State, **inputs) -> str:
    blueprint = yaml.load(BLUEPRINT.read_text(encoding="utf-8"), Loader=_Loader)  # noqa: S506 - SafeLoader subclass
    variables = {**INPUTS, **inputs, "trigger": {"from_state": old, "to_state": new}}
    return str(Template(blueprint["variables"]["message"], hass).async_render(variables)).strip()


async def test_blueprint_reports_what_went_wrong_once(hass: HomeAssistant, freezer) -> None:
    await hass.config.async_set_time_zone("Europe/Zurich")
    freezer.move_to(NOW)
    fine = _route(_con(6), _con(36))
    assert _message(hass, fine, fine) == ""

    late = _route(_con(6, delay=5), _con(36))
    assert _message(hass, fine, late) == "07:06 IC 6: +5 min"
    assert _message(hass, late, late) == ""  # told once
    assert _message(hass, late, _route(_con(6, delay=9), _con(36))) == ""  # still within the same five minutes
    assert _message(hass, late, _route(_con(6, delay=10), _con(36))) == "07:06 IC 6: +10 min"
    assert _message(hass, fine, _route(_con(6, delay=2), _con(36))) == ""  # below the minimum

    moved = _route(_con(6, dep_platform="9", dep_platform_planned="4", platform_changed=True), _con(36))
    assert _message(hass, fine, moved) == "07:06 IC 6: platform 9 instead of 4"
    assert _message(hass, moved, moved) == ""

    gone = _route(_con(6, cancelled=True, delay=12), _con(36))
    assert _message(hass, late, gone) == "07:06 IC 6: cancelled"  # the delay of a cancelled train is of no use
    assert _message(hass, None, gone) == "07:06 IC 6: cancelled"  # nothing known from before


async def test_blueprint_says_when_it_runs_as_planned_again(hass: HomeAssistant, freezer) -> None:
    await hass.config.async_set_time_zone("Europe/Zurich")
    freezer.move_to(NOW)
    late = _route(_con(6, delay=6))
    fine = _route(_con(6))
    assert _message(hass, late, fine) == "07:06 IC 6: as planned again"
    assert _message(hass, late, fine, all_clear=False) == ""
    # The train has left the list: nothing to say about it.
    assert _message(hass, late, _route(_con(36))) == ""


async def test_blueprint_watches_only_my_trains(hass: HomeAssistant, freezer) -> None:
    await hass.config.async_set_time_zone("Europe/Zurich")
    freezer.move_to(NOW)
    fine = _route(_con(6), _con(36), _con(66))
    late = _route(_con(6, delay=5), _con(36, delay=5), _con(66, delay=5))
    assert _message(hass, fine, late) == "07:06 IC 6: +5 min"  # 07:36 and 08:06 leave after 07:30
    assert _message(hass, fine, late, train_until="07:40:00") == "07:06 IC 6: +5 min\n07:36 IC 6: +5 min"
    assert _message(hass, fine, late, train_until="07:40:00", lead_minutes=20) == "07:06 IC 6: +5 min"


async def test_blueprint_reads_a_departure_board_too(hass: HomeAssistant, freezer) -> None:
    await hass.config.async_set_time_zone("Europe/Zurich")
    freezer.move_to(NOW)

    def stop(**over) -> State:
        row = {"departure_ts": ts(6), "line": "S", "to": "Thun", "delay": 0, "platform": "3",
               "platform_changed": False, "cancelled": False, **over}
        return State(BOARD_ENTITY, "2026-11-09T06:06:00+00:00", {"station_name": "Bern", "departures": [row]})

    assert _message(hass, stop(), stop(cancelled=True)) == "07:06 S → Thun: cancelled"
    assert _message(hass, stop(), stop(platform="5", platform_changed=True, delay=3)) == "07:06 S → Thun: platform 5, +3 min"
