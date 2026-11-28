"""Triggers for Swiss Transport.

"Next departure delayed", "Next departure cancelled", "Platform changed" and
"Disruption reported" for the automation editor's trigger list. All watch a
departure-board or saved-connection entity: the delay, the cancellation and
the platform change of the next departure (or connection) and the disruption
messages of the stop (real-time source) are attributes of those entities.
A target that expands to other entities (a device, an area) is narrowed to
the ones this integration created.

The trigger platform API arrived in Home Assistant 2026.10. On an older
version the module still imports, but offers no triggers.
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorDeviceClass
from homeassistant.const import CONF_FOR, CONF_OPTIONS, CONF_TARGET, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import DOMAIN

CONF_MINIMUM_DELAY = "minimum_delay"

try:
    from homeassistant.helpers.automation import DomainSpec
    from homeassistant.helpers.trigger import (
        ATTR_BEHAVIOR,
        BEHAVIOR_ALL,
        BEHAVIOR_EACH,
        BEHAVIOR_FIRST,
        EntityTriggerBase,
        Trigger,
    )
except ImportError:  # Home Assistant before 2026.10: no trigger platform API
    TRIGGERS: dict = {}
else:
    BOARD_DOMAIN_SPECS = {SENSOR_DOMAIN: DomainSpec(device_class=SensorDeviceClass.TIMESTAMP)}

    DELAY_SCHEMA = vol.Schema(
        {
            vol.Required(CONF_TARGET): cv.TARGET_FIELDS,
            vol.Required(CONF_OPTIONS, default={}): {
                vol.Required(ATTR_BEHAVIOR, default=BEHAVIOR_EACH): vol.In(
                    [BEHAVIOR_FIRST, BEHAVIOR_ALL, BEHAVIOR_EACH]
                ),
                vol.Optional(CONF_FOR): cv.positive_time_period,
                vol.Optional(CONF_MINIMUM_DELAY, default=5): vol.All(vol.Coerce(int), vol.Range(min=1, max=180)),
            },
        }
    )

    def _own_entities(hass: HomeAssistant, entities: set[str]) -> set[str]:
        """Keep only entities created by this integration."""
        registry = er.async_get(hass)
        return {
            entity_id
            for entity_id in entities
            if (entry := registry.async_get(entity_id)) is not None
            and entry.platform == DOMAIN
        }

    def _next_item(state: State) -> dict | None:
        """The next departure of a board, or the next connection of a route."""
        items = state.attributes.get("departures") or state.attributes.get("connections") or []
        return items[0] if items else None

    _GAP = (STATE_UNAVAILABLE, STATE_UNKNOWN)

    class _BoardTrigger(EntityTriggerBase):
        """Base of the two triggers: fires when a board starts to match.

        `_matches` says whether a board state shows what the trigger waits
        for; the trigger fires when a state matches and the one before it
        did not. The core skips every change out of "unavailable" or
        "unknown", and a board is unavailable while the timetable cannot be
        read - so a delay or a disruption that is there when the board comes
        back would never be reported. Such a change is let through and
        judged against the last state seen before the gap: it fires unless
        that state matched already, also when nothing is known from before.
        The core asks is_valid_state for every state with a value and only
        then is_valid_transition, so the match is remembered there.
        """

        _domain_specs = BOARD_DOMAIN_SPECS
        _excluded_from_states = frozenset()

        def __init__(self, hass: HomeAssistant, config) -> None:
            super().__init__(hass, config)
            self._last_match: dict[str, bool] = {}
            self._previous_match: dict[str, bool | None] = {}

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities))

        def _matches(self, state: State) -> bool:
            raise NotImplementedError

        def is_valid_state(self, state: State, report_not_triggered) -> bool:
            matches = self._matches(state)
            self._previous_match[state.entity_id] = self._last_match.get(state.entity_id)
            self._last_match[state.entity_id] = matches
            return matches

        def is_valid_transition(self, from_state: State, to_state: State) -> bool:
            if from_state.state in _GAP:
                return self._previous_match.get(to_state.entity_id) is not True
            return not self._matches(from_state)

    class _DepartureDelayed(_BoardTrigger):
        """The next departure (or connection) is delayed by at least N minutes.

        Fires when the delay reaches the minimum, not again while it stays
        there: a board that keeps refreshing with the same delay is quiet."""

        _schema = DELAY_SCHEMA

        def __init__(self, hass: HomeAssistant, config) -> None:
            super().__init__(hass, config)
            self._minimum = int(self._options.get(CONF_MINIMUM_DELAY) or 5)

        def _matches(self, state: State) -> bool:
            item = _next_item(state)
            delay = item.get("delay") if item else None
            return isinstance(delay, (int, float)) and int(delay) >= self._minimum

    class _DisruptionReported(_BoardTrigger):
        """A disruption message appears for the stop (real-time source)."""

        def _matches(self, state: State) -> bool:
            return bool(state.attributes.get("alerts"))

    def _journey(state: State) -> tuple:
        """What tells the next departure (or connection) from another one."""
        item = _next_item(state) or {}
        return (item.get("departure_ts"), item.get("line"), item.get("to"), tuple(item.get("products") or ()))

    class _JourneyTrigger(_BoardTrigger):
        """Fires for every journey it matches: also when the next departure
        matches right after another one that did (two cancelled trains in a
        row are two events, a delay that lasts is one)."""

        _flag = ""

        def _matches(self, state: State) -> bool:
            item = _next_item(state)
            return bool(item and item.get(self._flag))

        def is_valid_transition(self, from_state: State, to_state: State) -> bool:
            if from_state.state in _GAP:
                return super().is_valid_transition(from_state, to_state)
            return not self._matches(from_state) or _journey(from_state) != _journey(to_state)

    class _DepartureCancelled(_JourneyTrigger):
        """The next departure is cancelled. A saved connection knows this
        only with a departure board of its start station."""

        _flag = "cancelled"

    class _PlatformChanged(_JourneyTrigger):
        """The next departure (or connection) leaves from another platform
        than the timetable says."""

        _flag = "platform_changed"

    TRIGGERS: dict[str, type[Trigger]] = {
        "departure_delayed": _DepartureDelayed,
        "departure_cancelled": _DepartureCancelled,
        "platform_changed": _PlatformChanged,
        "disruption_reported": _DisruptionReported,
    }


async def async_get_triggers(hass: HomeAssistant) -> dict:
    """Return the triggers of this integration."""
    return TRIGGERS
