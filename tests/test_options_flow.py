"""The Configure dialog: number of rows, transport types, line labels and
the real-time token of a board; rows and line labels of a connection."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.swiss_transport.const import (
    CONF_DIRECTIONS,
    CONF_ENTRY_TYPE,
    CONF_FROM_ID,
    CONF_LIMIT,
    CONF_LINE_LABEL,
    CONF_OJP_TOKEN,
    CONF_STATION_ID,
    CONF_TO_ID,
    DOMAIN,
    ENTRY_TYPE_CONNECTION,
    OJP_ENDPOINT,
)

from .common import (
    BOARD_ENTITY,
    BOARD_URL,
    ROUTE_ENTITY,
    THUN,
    FakeApi,
    add_board,
    add_connection,
    ojp_event,
    ojp_xml,
    poll,
    setup,
)


def _defaults(result) -> dict:
    """The pre-filled values of a form."""
    return {str(key): key.default() for key in result["data_schema"].schema if key.default is not vol.UNDEFINED}


async def _open(hass: HomeAssistant, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert (result["type"], result["step_id"]) == (FlowResultType.FORM, "init")
    return result


async def test_board_options_are_saved_and_the_board_follows(hass: HomeAssistant, api: FakeApi) -> None:
    entry = await setup(hass, add_board(hass, transportations=["train"]))
    result = await _open(hass, entry)
    assert _defaults(result) == {
        CONF_LIMIT: 8,
        "transportations": ["train"],
        CONF_OJP_TOKEN: "",
        CONF_LINE_LABEL: "category",
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LIMIT: 3.0, "transportations": ["train", "tram"], CONF_OJP_TOKEN: "", CONF_LINE_LABEL: "full"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_LIMIT: 3, "transportations": ["train", "tram"], CONF_LINE_LABEL: "full"}
    assert api.requests(OJP_ENDPOINT) == []

    await hass.async_block_till_done()
    query = api.requests(BOARD_URL)[-1][1].query
    assert query["limit"] == "3"
    assert query.getall("transportations") == ["train", "tram"]
    attrs = hass.states.get(BOARD_ENTITY).attributes
    assert attrs["limit"] == 3
    assert [dep["line"] for dep in attrs["departures"]] == ["S9", "IC8"]


async def test_board_form_shows_what_is_stored(hass: HomeAssistant, api: FakeApi) -> None:
    add_connection(hass, options={CONF_OJP_TOKEN: "made-up-token"})
    entry = add_board(
        hass, transportations=["train"], options={CONF_LIMIT: 12, "transportations": ["bus"], CONF_LINE_LABEL: "number"}
    )
    assert _defaults(await _open(hass, entry)) == {
        CONF_LIMIT: 12,
        "transportations": ["bus"],
        CONF_OJP_TOKEN: "made-up-token",
        CONF_LINE_LABEL: "number",
    }


async def test_token_entered_in_the_options_is_checked_and_shared(hass: HomeAssistant, api: FakeApi) -> None:
    entry = add_board(hass)
    other = add_board(hass, entry_id="board0002", station=THUN)
    route = add_connection(hass)
    result = await _open(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LIMIT: 8, "transportations": [], CONF_OJP_TOKEN: " made-up-token ", CONF_LINE_LABEL: "category"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    probe = api.requests(OJP_ENDPOINT)[0]
    assert probe[3]["Authorization"] == "Bearer made-up-token"
    assert "<siri:StopPointRef>8507000</siri:StopPointRef>" in probe[2].decode("utf-8")
    for holder in (entry, other, route):
        assert holder.options[CONF_OJP_TOKEN] == "made-up-token"


async def test_emptied_token_field_removes_the_token_everywhere(hass: HomeAssistant, api: FakeApi) -> None:
    entry = add_board(hass, options={CONF_OJP_TOKEN: "made-up-token", CONF_LIMIT: 5})
    other = add_board(hass, entry_id="board0002", station=THUN, options={CONF_OJP_TOKEN: "made-up-token"})
    result = await _open(hass, entry)
    assert _defaults(result)[CONF_OJP_TOKEN] == "made-up-token"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LIMIT: 5, "transportations": [], CONF_OJP_TOKEN: "", CONF_LINE_LABEL: "category"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_OJP_TOKEN not in entry.options
    assert CONF_OJP_TOKEN not in other.options
    # four requests when the dialog opened (the lines and directions to choose
    # from: now and three later times), none to check a token that was taken out
    assert len(api.requests(OJP_ENDPOINT)) == 4


async def test_rejected_token_is_not_saved(hass: HomeAssistant, api: FakeApi) -> None:
    api.fail["ojp"] = 401
    entry = add_board(hass, options={CONF_LIMIT: 5})
    other = add_board(hass, entry_id="board0002", station=THUN)
    result = await _open(hass, entry)
    answers = {CONF_LIMIT: 9, "transportations": [], CONF_OJP_TOKEN: "made-up-token", CONF_LINE_LABEL: "full"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], answers)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.options == {CONF_LIMIT: 5}
    assert CONF_OJP_TOKEN not in other.options

    api.fail["ojp"] = 503
    result = await hass.config_entries.options.async_configure(result["flow_id"], answers)
    assert result["errors"] == {"base": "cannot_connect"}

    api.fail.clear()
    result = await hass.config_entries.options.async_configure(result["flow_id"], answers)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_LIMIT: 9, "transportations": [], CONF_OJP_TOKEN: "made-up-token", CONF_LINE_LABEL: "full"}
    assert other.options[CONF_OJP_TOKEN] == "made-up-token"


async def test_connection_options_keep_the_shared_token(hass: HomeAssistant, api: FakeApi) -> None:
    entry = await setup(hass, add_connection(hass, options={CONF_OJP_TOKEN: "made-up-token"}))
    result = await _open(hass, entry)
    assert _defaults(result) == {CONF_LIMIT: 6, CONF_LINE_LABEL: "category"}

    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_LIMIT: 3, CONF_LINE_LABEL: "number"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_OJP_TOKEN: "made-up-token", CONF_LIMIT: 3, CONF_LINE_LABEL: "number"}
    assert api.requests(OJP_ENDPOINT) == []

    await hass.async_block_till_done()
    attrs = hass.states.get(ROUTE_ENTITY).attributes
    assert attrs["limit"] == 3
    assert attrs["connections"][0]["legs"][0]["line"] == "6"


async def test_entries_without_a_stored_limit_start_from_the_defaults(hass: HomeAssistant, api: FakeApi) -> None:
    board = MockConfigEntry(domain=DOMAIN, title="Bern", data={CONF_STATION_ID: "8507000"})
    route = MockConfigEntry(
        domain=DOMAIN,
        title="Bern → Thun",
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_CONNECTION, CONF_FROM_ID: "8507000", CONF_TO_ID: "8507100"},
    )
    board.add_to_hass(hass)
    route.add_to_hass(hass)
    assert _defaults(await _open(hass, board))[CONF_LIMIT] == 8
    assert _defaults(await _open(hass, board))["transportations"] == []
    assert _defaults(await _open(hass, route))[CONF_LIMIT] == 6


# --- only some lines and directions --------------------------------------------

TRAMS = ojp_xml(
    [
        ojp_event(3, "Bahnhofplatz/HB", line="6", direction="H"),
        ojp_event(5, "Zoo", line="6", direction="R"),
        ojp_event(9, "Langmauerstrasse", line="6", direction="H"),  # a short turn, same direction
        ojp_event(13, "Bahnhofplatz/HB", line="6", direction="H"),
        ojp_event(7, "Triemli", line="33", direction="H", planned_quay="C"),
        ojp_event(8, "Somewhere"),  # no direction named: not offered
    ]
)


def _choices(result) -> dict[str, str]:
    """The lines and directions a form offers, id -> label."""
    for key, selector in result["data_schema"].schema.items():
        if str(key) == CONF_DIRECTIONS:
            return {option["value"]: option["label"] for option in selector.config["options"]}
    return {}


async def test_lines_and_directions_are_offered_with_a_token(hass: HomeAssistant, api: FakeApi) -> None:
    api.ojp = TRAMS
    entry = add_board(hass, options={CONF_OJP_TOKEN: "made-up-token"})
    result = await _open(hass, entry)
    # by line, labelled with the destination most journeys of that direction have
    # and, where the stop names its Haltekanten, with the one it leaves from
    assert _choices(result) == {"6|H": "6 → Bahnhofplatz/HB", "6|R": "6 → Zoo", "33|H": "33 → Triemli · C"}
    assert _defaults(result)[CONF_DIRECTIONS] == []
    asked = api.requests(OJP_ENDPOINT)[-1][2].decode("utf-8")
    assert "<NumberOfResults>60</NumberOfResults>" in asked

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_LIMIT: 8, "transportations": [], CONF_OJP_TOKEN: "made-up-token", CONF_LINE_LABEL: "category", CONF_DIRECTIONS: ["6|H", "33|H"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_DIRECTIONS] == ["6|H", "33|H"]


async def test_chosen_directions_stay_in_the_choice(hass: HomeAssistant, api: FakeApi) -> None:
    """A line that does not run right now, or a source that cannot be read:
    what is chosen is still shown and can be unticked."""
    api.ojp = TRAMS
    entry = add_board(hass, options={CONF_OJP_TOKEN: "made-up-token", CONF_DIRECTIONS: ["6|H", "N4|R"]})
    result = await _open(hass, entry)
    assert _choices(result)["N4|R"] == "N4 (R)" and "6|R" in _choices(result)
    assert _defaults(result)[CONF_DIRECTIONS] == ["6|H", "N4|R"]

    api.fail["ojp"] = 503
    result = await _open(hass, entry)
    assert _choices(result) == {"6|H": "6 (H)", "N4|R": "N4 (R)"}

    # emptied: the whole stop again
    api.fail.clear()
    result = await _open(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_LIMIT: 8, "transportations": [], CONF_OJP_TOKEN: "made-up-token", CONF_LINE_LABEL: "category", CONF_DIRECTIONS: []},
    )
    assert entry.options[CONF_DIRECTIONS] == []


async def test_the_dialog_looks_ahead_for_night_and_rush_hour_lines(hass: HomeAssistant, api: FakeApi) -> None:
    """Issue 7: the dialog is opened on a Monday morning; the night lines and
    the rush-hour lines are offered all the same, and the board remembers them."""
    api.ojp = TRAMS
    api.ojp_later = ojp_xml([ojp_event(900, "Bellevue", line="N4", direction="R"), ojp_event(40, "Zoo", line="6", direction="R")])
    entry = await setup(hass, add_board(hass, options={CONF_OJP_TOKEN: "made-up-token"}))
    before = len(api.requests(OJP_ENDPOINT))
    result = await _open(hass, entry)
    assert _choices(result) == {"N4|R": "N4 → Bellevue", "6|H": "6 → Bahnhofplatz/HB", "6|R": "6 → Zoo", "33|H": "33 → Triemli · C"}
    asked = [call[2].decode("utf-8") for call in api.requests(OJP_ENDPOINT)[before:]]
    # now, the same Monday at 07:30 and 17:30, the night to Saturday at 01:30 (Swiss time)
    assert sorted(body.partition("<DepArrTime>")[2].partition("<")[0] for body in asked) == [
        "",
        "2026-11-09T06:30:00Z",
        "2026-11-09T16:30:00Z",
        "2026-11-14T00:30:00Z",
    ]
    assert entry.runtime_data.seen_directions["N4|R"] == "N4 → Bellevue"

    # a look ahead that fails only leaves its lines out
    api.fail["ojp_later"] = 503
    api.ojp_later = ojp_xml([ojp_event(900, "Somewhere", line="N9", direction="H")])
    result = await _open(hass, entry)
    assert "N9|H" not in _choices(result) and "6|H" in _choices(result)


async def test_lines_seen_earlier_are_offered_too(hass: HomeAssistant, api: FakeApi, freezer, hass_storage) -> None:
    """Issue 7: a night line does not run when the dialog is opened, but the
    board has seen it: it is offered, with its label, also after a restart."""
    api.ojp = ojp_xml([ojp_event(3, "Bahnhofplatz/HB", line="6", direction="H"), ojp_event(4, "Bellevue", line="N4", direction="R")])
    entry = add_board(hass, options={CONF_OJP_TOKEN: "made-up-token"})
    await setup(hass, entry)
    assert entry.runtime_data.seen_directions == {"6|H": "6 → Bahnhofplatz/HB", "N4|R": "N4 → Bellevue"}

    # by day only the trams run; the label of a line that runs is the fresh one
    api.ojp = ojp_xml([ojp_event(3, "Zoo", line="6", direction="R"), ojp_event(5, "Langmauerstrasse", line="6", direction="H")])
    result = await _open(hass, entry)
    assert _choices(result) == {"N4|R": "N4 → Bellevue", "6|H": "6 → Langmauerstrasse", "6|R": "6 → Zoo"}

    # the real-time source cannot be read: what was seen is still offered
    api.fail["ojp"] = 503
    result = await _open(hass, entry)
    assert _choices(result) == {"N4|R": "N4 → Bellevue", "6|H": "6 → Bahnhofplatz/HB", "6|R": "6 → Zoo"}
    api.fail.clear()

    # written to disk after a while, read again after a restart
    await poll(hass, freezer)
    await poll(hass, freezer)
    key = f"swiss_transport.directions_{entry.entry_id}"
    assert hass_storage[key]["data"] == {"6|H": "6 → Bahnhofplatz/HB", "N4|R": "N4 → Bellevue", "6|R": "6 → Zoo"}
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert "N4|R" in entry.runtime_data.seen_directions

    # removing the station deletes what it remembered
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage


async def test_no_choice_of_directions_without_a_token(hass: HomeAssistant, api: FakeApi) -> None:
    """The direction comes from the real-time source: without a token the
    field is not shown, and what was chosen earlier is kept for later."""
    api.ojp = TRAMS
    entry = add_board(hass)
    result = await _open(hass, entry)
    assert _choices(result) == {} and api.requests(OJP_ENDPOINT) == []

    # nothing to choose from and nothing chosen: no field either
    api.ojp = ojp_xml()
    with_token = add_board(hass, entry_id="board0002", station=THUN, options={CONF_OJP_TOKEN: "made-up-token"})
    assert _choices(await _open(hass, with_token)) == {}

