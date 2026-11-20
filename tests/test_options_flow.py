"""The Configure dialog: number of rows, transport types, line labels and
the real-time token of a board; rows and line labels of a connection."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.swiss_transport.const import (
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
    assert api.requests(OJP_ENDPOINT) == []


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
