"""Automatic setup of a departure-board dashboard.

Creates one dashboard ("ÖV Abfahrten") with a Swiss Transport card per
configured station/connection, plus a full-width date/time & mode selector bar
on top. Uses Home Assistant's internal Lovelace storage API (no officially
documented integration API exists). Purely additive and idempotent — once the
user deletes the dashboard, that choice sticks.

The view uses the "sections" layout: the selector bar sits in a full-width
section, and every board gets its own section so they flow into columns below.
Cards are identified by their `entity` (mapping kept in a small persistent
store), so the card config stays free of foreign keys and the visual editor
keeps working on it.
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

from .const import (
    CONF_ENTRY_TYPE,
    DOMAIN,
    ENTRY_TYPE_CONNECTION,
    MODE_ENTITY_ID,
    TIME_ENTITY_ID,
)
from .localization import t

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL_PATH = "oev-abfahrten"
DASHBOARD_ICON = "mdi:train"
VIEW_PATH = "abfahrten"
CARD_TYPE_STATION = "custom:swiss-transport-card"
CARD_TYPE_CONNECTION = "custom:swiss-transport-connection-card"
CARD_TYPES = (CARD_TYPE_STATION, CARD_TYPE_CONNECTION)
CONTROL_CARD_TYPE = "custom:swiss-transport-controls-card"

_STORE_VERSION = 1
_STORE_KEY = f"{DOMAIN}.dashboard"


# --- card / section helpers ------------------------------------------------

def _control_card() -> dict:
    return {"type": CONTROL_CARD_TYPE}


def _is_control_card(card) -> bool:
    return isinstance(card, dict) and card.get("type") == CONTROL_CARD_TYPE


def _is_legacy_control_card(card) -> bool:
    """The first iteration used a plain entities card; recognise it so upgrades
    can replace it with the custom selector bar."""
    return (
        isinstance(card, dict)
        and card.get("type") == "entities"
        and any(
            (isinstance(e, dict) and e.get("entity") == MODE_ENTITY_ID) or e == MODE_ENTITY_ID
            for e in (card.get("entities") or [])
        )
    )


def _control_section() -> dict:
    """A full-width section holding the selector bar."""
    return {
        "type": "grid",
        "column_span": 4,
        "cards": [{**_control_card(), "layout_options": {"grid_columns": "full"}}],
    }


def _board_section(card: dict) -> dict:
    return {"type": "grid", "cards": [card]}


def _iter_cards(view: dict):
    for section in view.get("sections", []) or []:
        for card in section.get("cards", []) or []:
            yield card


def _has_board_card(view: dict, entity_id: str) -> bool:
    return any(
        isinstance(c, dict) and c.get("type") in CARD_TYPES and c.get("entity") == entity_id
        for c in _iter_cards(view)
    )


def _ensure_control_section(view: dict, hass: HomeAssistant) -> None:
    sections = view.setdefault("sections", [])
    if not any(any(_is_control_card(c) for c in s.get("cards", []) or []) for s in sections):
        sections.insert(0, _control_section())


def _new_view(hass: HomeAssistant) -> dict:
    return {
        "title": t("dashboard_title", hass),
        "path": VIEW_PATH,
        "type": "sections",
        "sections": [_control_section()],
    }


# --- dashboard lifecycle ---------------------------------------------------

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

    view_config = {"views": [_new_view(hass)]}
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
    await async_upgrade_dashboard_controls(hass)

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
        view = _new_view(hass)
        views.append(view)

    _ensure_control_section(view, hass)

    card_type = (
        CARD_TYPE_CONNECTION
        if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_CONNECTION
        else CARD_TYPE_STATION
    )
    if not _has_board_card(view, entity_id):
        view.setdefault("sections", []).append(
            _board_section(
                {
                    "type": card_type,
                    "entity": entity_id,
                    "datetime_entity": TIME_ENTITY_ID,
                    "mode_entity": MODE_ENTITY_ID,
                }
            )
        )
    await storage.async_save(config)

    store: Store = Store(hass, _STORE_VERSION, _STORE_KEY)
    data = await store.async_load() or {}
    card_map = data.setdefault("cards", {})
    if card_map.get(entry.entry_id) != entity_id:
        card_map[entry.entry_id] = entity_id
        await store.async_save(data)
    _LOGGER.info("Synced departures-dashboard card for %s", entity_id)


async def async_remove_station_card(hass: HomeAssistant, entry_id: str) -> None:
    """Remove a station's card (and its now-empty section) when its config
    entry is deleted."""
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

    view = next((v for v in (config or {}).get("views", []) if v.get("path") == VIEW_PATH), None)
    if view is None or entity_id is None:
        return
    if _remove_board_card(view, entity_id):
        await storage.async_save(config)
        _LOGGER.info("Removed departures-dashboard card for %s", entity_id)


def _remove_board_card(view: dict, entity_id: str) -> bool:
    """Drop the board card for entity_id; drop the section if it becomes empty.
    Returns True if anything changed."""
    sections = view.get("sections", [])
    changed = False
    new_sections = []
    for sec in sections:
        cards = sec.get("cards", []) or []
        kept = [
            c for c in cards
            if not (isinstance(c, dict) and c.get("type") in CARD_TYPES and c.get("entity") == entity_id)
        ]
        if len(kept) != len(cards):
            changed = True
        if kept:
            sec["cards"] = kept
            new_sections.append(sec)
        # else: empty board section is dropped
    if changed:
        view["sections"] = new_sections
    return changed


async def async_upgrade_dashboard_controls(hass: HomeAssistant) -> None:
    """One-time upgrade of pre-existing dashboards to the sections layout with
    the full-width selector bar and controls-linked cards. Guarded by a store
    flag so it runs once and never fights the user afterwards."""
    store: Store = Store(hass, _STORE_VERSION, _STORE_KEY)
    data = await store.async_load() or {}
    if data.get("controls_ui_v3"):
        return

    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None or DASHBOARD_URL_PATH not in lovelace_data.dashboards:
        return
    storage = lovelace_data.dashboards[DASHBOARD_URL_PATH]
    try:
        config = await storage.async_load(False)
    except HomeAssistantError:
        return

    view = next((v for v in (config or {}).get("views", []) if v.get("path") == VIEW_PATH), None)
    if view is not None:
        # Collect all non-control cards from either the old masonry layout or an
        # already-sectioned view, preserving anything the user added.
        carried: list[dict] = []
        if view.get("sections"):
            for sec in view["sections"]:
                for c in sec.get("cards", []) or []:
                    if not _is_control_card(c) and not _is_legacy_control_card(c):
                        carried.append(c)
        else:
            for c in view.get("cards", []) or []:
                if not _is_control_card(c) and not _is_legacy_control_card(c):
                    carried.append(c)
        # Point our boards at the shared controls.
        for c in carried:
            if isinstance(c, dict) and c.get("type") in CARD_TYPES and not c.get("mode_entity"):
                c["datetime_entity"] = TIME_ENTITY_ID
                c["mode_entity"] = MODE_ENTITY_ID
        # Rebuild as a sections view: full-width selector on top, one section
        # per carried card.
        view.pop("cards", None)
        view["type"] = "sections"
        view["sections"] = [_control_section()] + [_board_section(c) for c in carried]
        await storage.async_save(config)
        _LOGGER.info("Upgraded departures dashboard to the full-width selector layout")

    data["controls_ui_v3"] = True
    await store.async_save(data)


async def async_remove_orphan_cards(hass: HomeAssistant) -> None:
    """Once per start: drop board cards whose sensor no longer exists (catches
    the case where an entry was deleted while Lovelace wasn't ready)."""
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None or DASHBOARD_URL_PATH not in lovelace_data.dashboards:
        return
    storage = lovelace_data.dashboards[DASHBOARD_URL_PATH]
    try:
        config = await storage.async_load(False)
    except HomeAssistantError:
        return
    view = next((v for v in (config or {}).get("views", []) if v.get("path") == VIEW_PATH), None)
    if view is None:
        return
    registry = er.async_get(hass)

    def _orphan(c) -> bool:
        if not (isinstance(c, dict) and c.get("type") in CARD_TYPES):
            return False
        e = c.get("entity")
        if not isinstance(e, str) or not e:
            return False
        return registry.async_get(e) is None and hass.states.get(e) is None

    sections = view.get("sections", [])
    changed = False
    new_sections = []
    for sec in sections:
        cards = sec.get("cards", []) or []
        kept = [c for c in cards if not _orphan(c)]
        if len(kept) != len(cards):
            changed = True
        if kept:
            sec["cards"] = kept
            new_sections.append(sec)
    if changed:
        view["sections"] = new_sections
        await storage.async_save(config)
        _LOGGER.info("Removed orphaned departures-dashboard card(s)")
