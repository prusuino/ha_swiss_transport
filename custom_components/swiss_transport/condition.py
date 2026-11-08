"""Conditions for Swiss Transport.

"Next departure is delayed" and "Disruption reported" for the automation
editor's condition list, mirroring the triggers: the delay of the next
departure (or connection) and the disruption messages of the stop are
attributes of the departure-board and connection entities. As with the
triggers, a target that expands to other entities is narrowed to the ones
this integration created.

The condition platform API arrived in Home Assistant 2026.11. On an older
version the module still imports, but offers no conditions.
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
    from homeassistant.helpers.condition import (
        ATTR_BEHAVIOR,
        BEHAVIOR_ALL,
        BEHAVIOR_ANY,
        Condition,
        EntityConditionBase,
    )
except ImportError:  # Home Assistant before 2026.11: no condition platform API
    CONDITIONS: dict = {}
else:
    BOARD_DOMAIN_SPECS = {SENSOR_DOMAIN: DomainSpec(device_class=SensorDeviceClass.TIMESTAMP)}

    DELAY_SCHEMA = vol.Schema(
        {
            vol.Required(CONF_TARGET): cv.TARGET_FIELDS,
            vol.Required(CONF_OPTIONS, default={}): {
                vol.Required(ATTR_BEHAVIOR, default=BEHAVIOR_ANY): vol.In([BEHAVIOR_ANY, BEHAVIOR_ALL]),
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

    class _IsDepartureDelayed(EntityConditionBase):
        """The next departure (or connection) is delayed by at least N minutes."""

        _domain_specs = BOARD_DOMAIN_SPECS
        _schema = DELAY_SCHEMA

        def __init__(self, hass: HomeAssistant, config) -> None:
            super().__init__(hass, config)
            self._minimum = int((config.options or {}).get(CONF_MINIMUM_DELAY) or 5)

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities))

        def is_valid_state(self, entity_state: State) -> bool:
            item = _next_item(entity_state)
            delay = item.get("delay") if item else None
            return isinstance(delay, (int, float)) and int(delay) >= self._minimum

    class _HasDisruption(EntityConditionBase):
        """A disruption message is reported for the stop (real-time source)."""

        _domain_specs = BOARD_DOMAIN_SPECS

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities))

        def is_valid_state(self, entity_state: State) -> bool:
            return bool(entity_state.attributes.get("alerts"))

    CONDITIONS: dict[str, type[Condition]] = {
        "is_departure_delayed": _IsDepartureDelayed,
        "has_disruption": _HasDisruption,
    }


async def async_get_conditions(hass: HomeAssistant) -> dict:
    """Return the conditions of this integration."""
    return CONDITIONS
