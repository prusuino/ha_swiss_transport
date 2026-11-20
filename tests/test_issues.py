"""The repair-issue helper: an issue appears only after several failures
in a row, can be raised at once, and is withdrawn by a success or with the
entry."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.swiss_transport.const import DOMAIN
from custom_components.swiss_transport.issues import IssueReporter, async_clear_entry_issues

HOST = {"host": "transport.opendata.ch"}


def _issue(hass: HomeAssistant, issue_id: str):
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


async def test_issue_appears_on_the_third_failure_in_a_row(hass: HomeAssistant) -> None:
    reporter = IssueReporter(hass, "entry1", after=3)
    reporter.failure("unreachable", HOST)
    reporter.failure("unreachable", HOST)
    assert _issue(hass, "unreachable_entry1") is None
    reporter.failure("unreachable", HOST)
    issue = _issue(hass, "unreachable_entry1")
    assert issue.translation_key == "unreachable"
    assert issue.translation_placeholders == HOST
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.is_fixable is False
    assert issue.is_persistent is False


async def test_success_withdraws_the_issue_and_starts_the_count_again(hass: HomeAssistant) -> None:
    reporter = IssueReporter(hass, "entry1", after=2)
    reporter.failure("unreachable", HOST)
    reporter.failure("unreachable", HOST)
    assert _issue(hass, "unreachable_entry1") is not None
    reporter.clear("unreachable")
    assert _issue(hass, "unreachable_entry1") is None
    reporter.failure("unreachable", HOST)
    assert _issue(hass, "unreachable_entry1") is None


async def test_clearing_without_an_open_issue_only_resets_the_count(hass: HomeAssistant) -> None:
    reporter = IssueReporter(hass, "entry1", after=2)
    reporter.failure("unreachable")
    reporter.clear("unreachable")
    reporter.failure("unreachable")
    assert _issue(hass, "unreachable_entry1") is None


async def test_single_call_can_ask_for_fewer_failures(hass: HomeAssistant) -> None:
    reporter = IssueReporter(hass, "entry1", after=3)
    reporter.failure("unreachable", HOST, after=1)
    assert _issue(hass, "unreachable_entry1") is not None


async def test_issue_can_be_raised_at_once_and_placeholders_become_text(hass: HomeAssistant) -> None:
    reporter = IssueReporter(hass, "entry1")
    reporter.raise_now("station_gone", {"station": 8507000})
    issue = _issue(hass, "station_gone_entry1")
    assert issue.translation_key == "station_gone"
    assert issue.translation_placeholders == {"station": "8507000"}
    reporter.clear("station_gone")
    assert _issue(hass, "station_gone_entry1") is None


async def test_suffix_keeps_the_issues_of_one_key_apart(hass: HomeAssistant) -> None:
    reporter = IssueReporter(hass, "entry1", after=1)
    reporter.failure("unreachable", HOST, suffix="board")
    reporter.failure("unreachable", HOST, suffix="realtime")
    assert _issue(hass, "unreachable_board_entry1") is not None
    assert _issue(hass, "unreachable_realtime_entry1") is not None
    reporter.clear("unreachable", suffix="board")
    assert _issue(hass, "unreachable_board_entry1") is None
    assert _issue(hass, "unreachable_realtime_entry1") is not None


async def test_issues_of_an_entry_are_withdrawn_together(hass: HomeAssistant) -> None:
    mine = IssueReporter(hass, "entry1", after=1)
    theirs = IssueReporter(hass, "entry2", after=1)
    mine.failure("unreachable", HOST)
    mine.raise_now("station_gone", suffix="8507000")
    theirs.failure("unreachable", HOST)
    ir.async_create_issue(
        hass, "another_integration", "unreachable_entry1", is_fixable=False, severity=ir.IssueSeverity.WARNING,
        translation_key="unreachable",
    )
    async_clear_entry_issues(hass, "entry1")
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, "unreachable_entry1") is None
    assert registry.async_get_issue(DOMAIN, "station_gone_8507000_entry1") is None
    assert registry.async_get_issue(DOMAIN, "unreachable_entry2") is not None
    assert registry.async_get_issue("another_integration", "unreachable_entry1") is not None
