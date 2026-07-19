"""Automatic setup of a departure-board dashboard.

Creates one dashboard ("ÖV Abfahrten") with a Swiss Transport card per
configured station. Uses Home Assistant's internal Lovelace storage API
(no officially documented integration API exists). Purely additive and
idempotent — once the user deletes the dashboard, that choice sticks.

Cards are identified by their `entity` (mapping kept in a small persistent
store), so the card config stays free of foreign keys and Home Assistant's
visual editor keeps working on it.
"""
from __future__ import annotations

import logging

from homeassistant.components import frontend
from homeassistant.components.lovelace import dashboard as ll_dashboard
from homeassistant.components.lovelace.const import (
    CONF_ALLOW_SINGLE_WORD,
    CONF_ICON,
    CONF_REQUIRE_ADMIN,
    CONF_SHOW_IN_SIDEBAR,
    CONF_TITLE,
    CONF_URL_PATH,
    DOMAIN as LOVELACE_DOMAIN,
    LOVELACE_DATA,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_CONNECTION
from .localization import t

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL_PATH = "oev-abfahrten"
DASHBOARD_ICON = "mdi:train"
VIEW_PATH = "abfahrten"
CARD_TYPE_STATION = "custom:swiss-transport-card"
CARD_TYPE_CONNECTION = "custom:swiss-transport-connection-card"
CARD_TYPES = (CARD_TYPE_STATION, CARD_TYPE_CONNECTION)

_STORE_VERSION = 1
_STORE_KEY = f"{DOMAIN}.dashboard"


async def async_ensure_dashboard(hass: HomeAssistant) -> None:
    """Create the dashboard once (idempotent). If the user deleted it, the
    stored marker prevents re-creation."""
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None:
        _LOGGER.warning("Lovelace data not available — could not set up the departures dashboard")
        return

    store: Store = Store(hass, _STORE_VERSION, _STORE_KEY)
    marker = await store.async_load()

    if DASHBOARD_URL_PATH in lovelace_data.dashboards:
        if not (marker and marker.get("created")):
            await store.async_save({**(marker or {}), "created": True})
        return

    if marker and marker.get("created"):
        _LOGGER.debug("Departures dashboard was deleted by the user — not re-creating it")
        return

    title = t("dashboard_title", hass)
    collection = ll_dashboard.DashboardsCollection(hass)
    await collection.async_load()
    try:
        item = await collection.async_create_item(
            {
                CONF_URL_PATH: DASHBOARD_URL_PATH,
                CONF_TITLE: title,
                CONF_ICON: DASHBOARD_ICON,
                CONF_SHOW_IN_SIDEBAR: True,
                CONF_REQUIRE_ADMIN: False,
                CONF_ALLOW_SINGLE_WORD: True,
            }
        )
    except Exception as err:  # noqa: BLE001 - dashboard creation must never break setup
        _LOGGER.warning("Could not create the departures dashboard: %s", err)
        return

    view_config = {
        "views": [
            {
                "title": title,
                "path": VIEW_PATH,
                "type": "masonry",
                "cards": [],
            }
        ]
    }
    storage = ll_dashboard.LovelaceStorage(hass, item)
    lovelace_data.dashboards[DASHBOARD_URL_PATH] = storage
    await storage.async_save(view_config)

    frontend.async_register_built_in_panel(
        hass,
        LOVELACE_DOMAIN,
        frontend_url_path=DASHBOARD_URL_PATH,
        require_admin=False,
        show_in_sidebar=True,
        sidebar_title=title,
        sidebar_icon=DASHBOARD_ICON,
        config={"mode": "storage"},
        update=False,
    )
    await store.async_save({**(marker or {}), "created": True})
    _LOGGER.info("Departures dashboard set up automatically at /%s", DASHBOARD_URL_PATH)


async def async_add_station_card(hass: HomeAssistant, entry: ConfigEntry, entity_id: str) -> None:
    """Add a Swiss Transport card for one station to the dashboard (idempotent
    per entity). Never touches other cards the user has added."""
    await async_ensure_dashboard(hass)

    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None or DASHBOARD_URL_PATH not in lovelace_data.dashboards:
        return
    storage = lovelace_data.dashboards[DASHBOARD_URL_PATH]
    try:
        config = await storage.async_load(False)
    except HomeAssistantError:
        return

    views = config.setdefault("views", [])
    view = next((v for v in views if v.get("path") == VIEW_PATH), None)
    if view is None:
        view = {"title": t("dashboard_title", hass), "path": VIEW_PATH, "type": "masonry", "cards": []}
        views.append(view)

    card_type = (
        CARD_TYPE_CONNECTION
        if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_CONNECTION
        else CARD_TYPE_STATION
    )
    cards = view.setdefault("cards", [])
    already = any(
        isinstance(c, dict) and c.get("type") in CARD_TYPES and c.get("entity") == entity_id
        for c in cards
    )
    if not already:
        cards.append({"type": card_type, "entity": entity_id})
        await storage.async_save(config)

    store: Store = Store(hass, _STORE_VERSION, _STORE_KEY)
    data = await store.async_load() or {}
    card_map = data.setdefault("cards", {})
    if card_map.get(entry.entry_id) != entity_id:
        card_map[entry.entry_id] = entity_id
        await store.async_save(data)
    _LOGGER.info("Synced departures-dashboard card for %s", entity_id)


async def async_remove_station_card(hass: HomeAssistant, entry_id: str) -> None:
    """Remove a station's card when its config entry is deleted; drop the
    view/dashboard reference if it ends up empty."""
    store: Store = Store(hass, _STORE_VERSION, _STORE_KEY)
    data = await store.async_load() or {}
    card_map = data.get("cards") or {}
    entity_id = card_map.pop(entry_id, None)
    if entity_id is not None:
        data["cards"] = card_map
        await store.async_save(data)

    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None or DASHBOARD_URL_PATH not in lovelace_data.dashboards:
        return
    storage = lovelace_data.dashboards[DASHBOARD_URL_PATH]
    try:
        config = await storage.async_load(False)
    except HomeAssistantError:
        return

    views = (config or {}).get("views", [])
    view = next((v for v in views if v.get("path") == VIEW_PATH), None)
    if view is None or entity_id is None:
        return
    cards = view.get("cards", [])
    remaining = [
        c for c in cards
        if not (isinstance(c, dict) and c.get("type") in CARD_TYPES and c.get("entity") == entity_id)
    ]
    if len(remaining) == len(cards):
        return
    view["cards"] = remaining
    await storage.async_save(config)
    _LOGGER.info("Removed departures-dashboard card for %s", entity_id)


async def async_remove_orphan_cards(hass: HomeAssistant) -> None:
    """Once per start: drop cards whose sensor no longer exists (catches the
    case where an entry was deleted while Lovelace wasn't ready)."""
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None or DASHBOARD_URL_PATH not in lovelace_data.dashboards:
        return
    storage = lovelace_data.dashboards[DASHBOARD_URL_PATH]
    try:
        config = await storage.async_load(False)
    except HomeAssistantError:
        return
    views = (config or {}).get("views", [])
    view = next((v for v in views if v.get("path") == VIEW_PATH), None)
    if view is None:
        return
    registry = er.async_get(hass)

    def _orphan(c: dict) -> bool:
        if not (isinstance(c, dict) and c.get("type") in CARD_TYPES):
            return False
        e = c.get("entity")
        if not isinstance(e, str) or not e:
            return False
        return registry.async_get(e) is None and hass.states.get(e) is None

    cards = view.get("cards", [])
    remaining = [c for c in cards if not _orphan(c)]
    if len(remaining) == len(cards):
        return
    view["cards"] = remaining
    await storage.async_save(config)
    _LOGGER.info("Removed %d orphaned departures-dashboard card(s)", len(cards) - len(remaining))
