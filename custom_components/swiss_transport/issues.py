"""Repair issues: a notice under Settings → Repairs when something needs the
user, or when a problem has lasted long enough to be worth a word.

Two kinds are raised here. A transport failure (the service does not
answer) becomes an issue only after several refreshes in a row, since one
network hiccup is not worth a notice, and it disappears on its own with the
next successful refresh. A configuration that no longer matches the data (a
station or region that is gone) is raised at once and stays until the entry
is reconfigured or the item is back. Issues are not persistent: a restart
clears them, and the next refresh raises them again if the problem is
still there.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN


class IssueReporter:
    """Raises and clears the repair issues of one config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str, after: int = 3) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._after = after
        self._counts: dict[str, int] = {}
        self._open: set[str] = set()

    def _issue_id(self, key: str, suffix: str | None) -> str:
        return f"{key}_{suffix}_{self._entry_id}" if suffix else f"{key}_{self._entry_id}"

    @callback
    def failure(
        self,
        key: str,
        placeholders: dict[str, str] | None = None,
        *,
        after: int | None = None,
        suffix: str | None = None,
    ) -> None:
        """Count a failure; raise the issue once it has happened `after`
        times in a row."""
        issue_id = self._issue_id(key, suffix)
        count = self._counts.get(issue_id, 0) + 1
        self._counts[issue_id] = count
        if count >= (after or self._after):
            self.raise_now(key, placeholders, suffix=suffix)

    @callback
    def raise_now(
        self, key: str, placeholders: dict[str, str] | None = None, *, suffix: str | None = None
    ) -> None:
        issue_id = self._issue_id(key, suffix)
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=key,
            translation_placeholders={k: str(v) for k, v in (placeholders or {}).items()},
        )
        self._open.add(issue_id)

    @callback
    def clear(self, key: str, *, suffix: str | None = None) -> None:
        """Forget the failures of a key and withdraw its issue if one is open."""
        issue_id = self._issue_id(key, suffix)
        self._counts.pop(issue_id, None)
        if issue_id in self._open:
            self._open.discard(issue_id)
            ir.async_delete_issue(self._hass, DOMAIN, issue_id)


@callback
def async_clear_entry_issues(hass: HomeAssistant, entry_id: str) -> None:
    """Withdraw every issue of an entry (on unload or removal)."""
    registry = ir.async_get(hass)
    for domain, issue_id in list(registry.issues):
        if domain == DOMAIN and issue_id.endswith(f"_{entry_id}"):
            ir.async_delete_issue(hass, DOMAIN, issue_id)
