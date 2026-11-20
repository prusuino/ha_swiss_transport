"""The diagnostics download: what it tells about the entry, the last fetch
and the entities, and what it keeps to itself (coordinates, the address,
the real-time token, the entry title)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.swiss_transport.const import DOMAIN
from custom_components.swiss_transport.diagnostics import (
    REDACTED,
    _compact,
    async_get_config_entry_diagnostics,
)

from .common import (
    BOARD_ENTITY,
    ROUTE_ENTITY,
    FakeApi,
    add_board,
    add_connection,
    board,
    departure,
    ojp_situation,
    ojp_xml,
    poll,
    setup,
    state_time,
)


async def test_board_diagnostics_keep_places_and_the_token_private(hass: HomeAssistant, api: FakeApi) -> None:
    entry = await setup(hass, add_board(hass, options={"ojp_token": "made-up-token", "limit": 5}))
    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["entry"]["title"] == REDACTED
    assert diag["entry"]["unique_id"] == REDACTED
    assert diag["entry"]["version"] == 1
    assert diag["entry"]["state"] == "ConfigEntryState.LOADED"
    assert diag["entry"]["data"]["station_id"] == "8507000"
    assert diag["entry"]["options"] == {"ojp_token": REDACTED, "limit": 5}

    fetched = diag["coordinators"]["coordinator"]
    assert fetched["last_update_success"] is True
    assert fetched["last_exception"] is None
    assert fetched["update_interval_seconds"] == 90
    assert fetched["data"]["latitude"] == REDACTED
    assert fetched["data"]["longitude"] == REDACTED
    assert fetched["data"]["address"] == REDACTED
    assert fetched["data"]["realtime"] is True
    assert [dep["line"] for dep in fetched["data"]["departures"]] == ["S", "IC"]

    entities = {entity["entity_id"]: entity for entity in diag["entities"]}
    sensor = entities[BOARD_ENTITY]
    assert sensor["unique_id"] == "board0001_departures"
    assert sensor["state"] == state_time(4)
    assert sensor["disabled_by"] is None
    assert sensor["attributes"]["latitude"] == REDACTED
    assert sensor["attributes"]["address"] == REDACTED
    assert sensor["attributes"]["departure_count"] == 2
    assert set(entities) == {BOARD_ENTITY, "datetime.swiss_transport_time", "select.swiss_transport_mode"}

    text = json.dumps(diag)
    for private in ("made-up-token", "Bahnhofplatz", "46.949", "7.439", "Departures Bern", "station_8507000"):
        assert private not in text, private


async def test_connection_diagnostics_show_the_route(hass: HomeAssistant, api: FakeApi) -> None:
    entry = await setup(hass, add_connection(hass))
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["entry"]["data"]["from_id"] == "8507000"
    fetched = diag["coordinators"]["coordinator"]
    assert fetched["update_interval_seconds"] == 300
    assert len(fetched["data"]["connections"]) == 2
    assert [entity["entity_id"] for entity in diag["entities"] if entity["entity_id"].startswith("sensor.")] == [ROUTE_ENTITY]
    json.dumps(diag)


async def test_long_lists_and_texts_are_cut_and_counted(hass: HomeAssistant, api: FakeApi) -> None:
    api.board = board([departure(minutes) for minutes in range(1, 31)])
    api.ojp = ojp_xml(situations=[ojp_situation("Replacement buses. " * 30)])
    entry = await setup(hass, add_board(hass, options={"ojp_token": "made-up-token"}))
    diag = await async_get_config_entry_diagnostics(hass, entry)
    data = diag["coordinators"]["coordinator"]["data"]
    assert len(data["departures"]) == 26
    assert data["departures"][-1] == "… 5 more (30 total)"
    assert len(data["alerts"][0]) == 301
    assert data["alerts"][0].endswith("…")


async def test_failed_refresh_is_named_by_its_type_only(hass: HomeAssistant, api: FakeApi, freezer) -> None:
    entry = await setup(hass, add_board(hass))
    api.fail["board"] = 500
    await poll(hass, freezer)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    fetched = diag["coordinators"]["coordinator"]
    assert fetched["last_update_success"] is False
    assert fetched["last_exception"] == "UpdateFailed"
    assert "transport.opendata.ch" not in json.dumps(fetched["last_exception"])


async def test_entry_that_is_not_loaded_still_gives_diagnostics(hass: HomeAssistant, api: FakeApi) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Stop at the corner", data={"station_id": "8507000", "name": "Stop at the corner", "location": ""}
    )
    entry.add_to_hass(hass)
    orphan = er.async_get(hass).async_get_or_create("sensor", DOMAIN, "left_over", config_entry=entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["entry"]["unique_id"] is None
    assert diag["entry"]["data"] == {"station_id": "8507000", "name": REDACTED, "location": ""}
    assert diag["coordinators"] == {}
    assert diag["entities"] == [
        {
            "entity_id": orphan.entity_id,
            "unique_id": "left_over",
            "disabled_by": None,
            "hidden_by": None,
            "state": None,
            "attributes": None,
        }
    ]


@dataclass
class _Stop:
    name: str
    latitude: float


def test_values_json_cannot_carry_are_converted() -> None:
    moment = datetime(2026, 11, 9, 7, 12, tzinfo=timezone.utc)
    compact = _compact(
        {
            "when": moment,
            "day": date(2026, 11, 9),
            "interval": timedelta(seconds=90),
            "stop": _Stop("Bern", 46.949),
            "types": {"train"},
            "pair": ("IC", 8),
            "other": complex(1, 2),
            "Latitude": 46.949,
            "lon": None,
            7: "numbered key",
        }
    )
    assert compact == {
        "when": "2026-11-09T07:12:00+00:00",
        "day": "2026-11-09",
        "interval": 90.0,
        "stop": {"name": "Bern", "latitude": REDACTED},
        "types": ["train"],
        "pair": ["IC", 8],
        "other": "(1+2j)",
        "Latitude": REDACTED,
        "lon": None,
        "7": "numbered key",
    }
    json.dumps(compact)


def test_wide_and_deep_structures_are_cut() -> None:
    wide = _compact({f"key{number:02d}": number for number in range(30)})
    assert len(wide) == 26
    assert wide["…"] == "5 more keys (30 total)"

    deep: dict = {}
    level = deep
    for _ in range(12):
        level["inner"] = {}
        level = level["inner"]
    compact = _compact(deep)
    for _ in range(9):
        compact = compact["inner"]
    assert compact == "…"
