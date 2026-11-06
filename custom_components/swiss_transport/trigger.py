"""Triggers for Swiss Transport.

"Next departure delayed" and "Disruption reported" for the automation
editor's trigger list. Both watch a departure-board or saved-connection
entity: the delay of the next departure (or connection) and the disruption
messages of the stop (real-time source) are attributes of those entities.
A target that expands to other entities (a device, an area) is narrowed to
the ones this integration created.

The trigger platform API arrived in Home Assistant 2026.10. On an older
version the module still imports, but offers no triggers.
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorDeviceClass
from homeassistant.const import CONF_FOR, CONF_OPTIONS, CONF_TARGET
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

    class _DepartureDelayed(EntityTriggerBase):
        """The next departure (or connection) is delayed by at least N minutes.

        Fires when the delay reaches the minimum, not again while it stays
        there: a board that keeps refreshing with the same delay is quiet."""

        _domain_specs = BOARD_DOMAIN_SPECS
        _schema = DELAY_SCHEMA

        def __init__(self, hass: HomeAssistant, config) -> None:
            super().__init__(hass, config)
            self._minimum = int(self._options.get(CONF_MINIMUM_DELAY) or 5)

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities))

        def _delay(self, state: State) -> int | None:
            item = _next_item(state)
            delay = item.get("delay") if item else None
            return int(delay) if isinstance(delay, (int, float)) else None

        def is_valid_state(self, state: State, report_not_triggered) -> bool:
            delay = self._delay(state)
            return delay is not None and delay >= self._minimum

        def is_valid_transition(self, from_state: State, to_state: State) -> bool:
            return not self.is_valid_state(from_state, lambda *a, **k: None)

    class _DisruptionReported(EntityTriggerBase):
        """A disruption message appears for the stop (real-time source)."""

        _domain_specs = BOARD_DOMAIN_SPECS

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities))

        def is_valid_state(self, state: State, report_not_triggered) -> bool:
            return bool(state.attributes.get("alerts"))

        def is_valid_transition(self, from_state: State, to_state: State) -> bool:
            return not bool(from_state.attributes.get("alerts"))

    TRIGGERS: dict[str, type[Trigger]] = {
        "departure_delayed": _DepartureDelayed,
        "disruption_reported": _DisruptionReported,
    }


async def async_get_triggers(hass: HomeAssistant) -> dict:
    """Return the triggers of this integration."""
    return TRIGGERS
