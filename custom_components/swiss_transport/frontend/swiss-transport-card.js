/* swiss-transport-card — a departure board (Abfahrtstafel) for a Swiss
 * Transport station sensor: one row per upcoming departure with a colored
 * line badge, destination, platform, countdown, and delay. Vanilla JS +
 * Shadow DOM, no dependencies. */

const LANG_FALLBACK = "en";

// Column headers, mirroring a real departure board (Zeit · Nach · Gleis ·
// Hinweis; the symbol column is unlabeled).
const HDR_TIME = { de: "Zeit", en: "Time", fr: "Heure", it: "Ora" };
const HDR_IN = { de: "in", en: "in", fr: "dans", it: "tra" };
const HDR_TO = { de: "Nach", en: "To", fr: "Direction", it: "Direzione" };
const HDR_PLATFORM = { de: "Gleis", en: "Platform", fr: "Voie", it: "Binario" };
const HDR_INFO = { de: "Hinweis", en: "Info", fr: "Info", it: "Info" };
const NOW_WORD = { de: "jetzt", en: "now", fr: "maint.", it: "ora" };
const LATE_FMT = {
  de: "+{n} Min",
  en: "+{n} min",
  fr: "+{n} min",
  it: "+{n} min",
};
const NO_DEP_WORD = {
  de: "Keine Abfahrten",
  en: "No departures",
  fr: "Aucun départ",
  it: "Nessuna partenza",
};
// Small label shown top-right of each card, naming what it is.
const TYPE_DEPARTURES = { de: "Abfahrten", en: "Departures", fr: "Départs", it: "Partenze" };
const TYPE_CONNECTION = { de: "Verbindung", en: "Connection", fr: "Liaison", it: "Collegamento" };

const LOCALE = { de: "de-CH", en: "en-GB", fr: "fr-CH", it: "it-CH" };

/* Current date and time, formatted for the card language. */
function nowParts(lang) {
  const loc = LOCALE[lang] || "de-CH";
  const now = new Date();
  return {
    date: now.toLocaleDateString(loc, { weekday: "long", day: "2-digit", month: "2-digit", year: "numeric" }),
    time: now.toLocaleTimeString(loc, { hour: "2-digit", minute: "2-digit" }),
  };
}

/* Shared CSS for the clock bar + header row, used by both cards. */
const HEAD_CSS = `
  .clockbar {
    display: flex; justify-content: space-between; align-items: baseline;
    font-size: 0.8em; color: var(--secondary-text-color);
    padding-bottom: 6px; margin-bottom: 8px;
    border-bottom: 1px solid var(--divider-color, rgba(127,127,127,.2));
  }
  .clockbar .time { font-weight: 600; font-variant-numeric: tabular-nums; }
  .headrow { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
  .typelabel {
    flex: none; font-size: 0.75em; font-weight: 600; letter-spacing: .03em;
    text-transform: uppercase; color: var(--secondary-text-color);
  }`;

/* Transport mode from the product category, driving the pictogram + color. */
function transportMode(category) {
  const c = (category || "").toUpperCase();
  if (["T", "TRM", "NFT"].includes(c)) return "tram";
  if (["B", "BUS", "NFB", "EXB", "KB"].includes(c)) return "bus";
  if (["BAT", "SHIP"].includes(c)) return "ship";
  if (["GB", "FUN", "PB", "CC", "SL"].includes(c)) return "cableway";
  return "train";
}

const MODE_ICON = {
  train: "mdi:train",
  tram: "mdi:tram",
  bus: "mdi:bus",
  ship: "mdi:ferry",
  cableway: "mdi:gondola",
};
const MODE_COLOR = {
  train: "#2b6cb0",
  tram: "#2e7d32",
  bus: "#00558c",
  ship: "#0277bd",
  cableway: "#6a1b9a",
};

/* Line-badge product class, following the common Swiss departure-board
 * styling: the S-Bahn gets a white chip with a border and dark text, the
 * InterCity/InterRegio family a red chip with white text, everything else a
 * filled chip in its transport-mode color. */
function productClass(category) {
  const c = (category || "").toUpperCase();
  if (c === "S" || c === "SN") return "sbahn";
  if (["IC", "ICE", "EC", "IR", "IRE", "RE", "R", "PE", "TGV", "RJ", "RJX", "EN", "NJ", "ICN", "VAE"].includes(c)) {
    return "ir";
  }
  return "other";
}

class SwissTransportCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) {
      throw new Error("swiss-transport-card: 'entity' is required");
    }
    this._config = config;
    if (!this._root) this._root = this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  connectedCallback() {
    // Keep the clock and countdown fresh even when no state changes arrive.
    this._timer = setInterval(() => this._render(), 30000);
  }

  disconnectedCallback() {
    if (this._timer) clearInterval(this._timer);
  }

  static getConfigElement() {
    return document.createElement("swiss-transport-card-editor");
  }

  static getStubConfig(hass, entities) {
    const e = (entities || []).find((x) => x.startsWith("sensor.swiss_transport_"));
    return { entity: e || "" };
  }

  getCardSize() {
    const deps = this._departures();
    return 1 + Math.min(deps.length || 3, this._maxRows());
  }

  _lang() {
    const l = ((this._hass && this._hass.language) || LANG_FALLBACK).split("-")[0];
    return ["de", "en", "fr", "it"].includes(l) ? l : LANG_FALLBACK;
  }

  _maxRows() {
    const n = parseInt(this._config.rows, 10);
    return Number.isFinite(n) && n > 0 ? n : 8;
  }

  _departures() {
    const st = this._hass && this._hass.states[this._config.entity];
    const deps = st && st.attributes && st.attributes.departures;
    return Array.isArray(deps) ? deps : [];
  }

  _render() {
    if (!this._hass || !this._config) return;
    const lang = this._lang();
    const st = this._hass.states[this._config.entity];
    const title =
      this._config.title ||
      (st && st.attributes && st.attributes.station_name) ||
      (st && st.attributes && st.attributes.friendly_name) ||
      "";
    const address = (st && st.attributes && st.attributes.address) || "";
    const now = nowParts(lang);
    const deps = this._departures().slice(0, this._maxRows());
    const nowMs = Date.now();
    // Hide the platform column entirely when not a single departure has one
    // (bus/tram stops). The destination column flexes to fill the card, so
    // nothing overflows regardless.
    const anyPlatform = deps.some((d) => d.platform);
    const cols = anyPlatform
      ? "auto auto auto minmax(80px, 1fr) auto auto"
      : "auto auto auto minmax(80px, 1fr) auto";

    const header = `
      <div class="cell hdr"></div>
      <div class="cell hdr">${HDR_TIME[lang] || HDR_TIME.en}</div>
      <div class="cell hdr">${HDR_IN[lang] || HDR_IN.en}</div>
      <div class="cell hdr">${HDR_TO[lang] || HDR_TO.en}</div>
      ${anyPlatform ? `<div class="cell hdr">${HDR_PLATFORM[lang] || HDR_PLATFORM.en}</div>` : ""}
      <div class="cell hdr">${HDR_INFO[lang] || HDR_INFO.en}</div>`;

    const rows = deps
      .map((d) => {
        const m = transportMode(d.category);
        const pcls = productClass(d.category);
        // Train line reads "IR 55" / "S23"; bus/tram badge is just the line.
        const badgeText =
          m === "train" && d.category && d.number
            ? `${d.category} ${d.number}`
            : d.line || d.category || "?";
        const badgeStyle = pcls === "other" ? `background:${MODE_COLOR[m]};color:#fff;` : "";
        const delay = Number.isFinite(d.delay) ? d.delay : null;
        const timeStr = d.departure ? String(d.departure).substr(11, 5) : "";
        // Countdown to the real (delay-adjusted) departure.
        const depMs = (d.departure_ts || 0) * 1000 + (delay ? delay * 60000 : 0);
        const minsLeft = Math.round((depMs - nowMs) / 60000);
        const countdown = minsLeft <= 0 ? (NOW_WORD[lang] || NOW_WORD.en) : `${minsLeft}′`;
        const hint =
          delay && delay > 0
            ? (LATE_FMT[lang] || LATE_FMT.en).replace("{n}", delay)
            : "";
        return `
          <div class="cell linecell">
            <ha-icon class="mode" icon="${MODE_ICON[m]}" style="color:${MODE_COLOR[m]};"></ha-icon>
            <div class="badge ${pcls}" style="${badgeStyle}">${this._escape(badgeText)}</div>
          </div>
          <div class="cell zeit">${this._escape(timeStr)}</div>
          <div class="cell cd">${this._escape(countdown)}</div>
          <div class="cell to"><span class="totxt">${this._escape(d.to || "")}</span></div>
          ${anyPlatform ? `<div class="cell platform${d.platform_changed ? " chg" : ""}">${this._escape(d.platform || "")}</div>` : ""}
          <div class="cell hint">${this._escape(hint)}</div>`;
      })
      .join("");

    this._root.innerHTML = `
      <style>
        .wrap { padding: 10px 14px 12px; }
        ${HEAD_CSS}
        .title {
          font-size: 1.15em; font-weight: 500;
          color: var(--primary-text-color);
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .addr {
          font-size: 0.85em; color: var(--secondary-text-color);
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .head { margin-bottom: 8px; }
        .board {
          display: grid;
          /* Real-board column order: symbol · Zeit · in · Nach · Gleis ·
           * Hinweis. The destination flexes (1fr) so the card never overflows;
           * grid-template-columns is set inline (the Gleis column is dropped
           * for bus/tram stops). */
          column-gap: 12px; align-items: center;
        }
        .cell {
          display: flex; align-items: center; min-height: 34px;
          padding: 4px 0;
          border-top: 1px solid var(--divider-color, rgba(127,127,127,.2));
          font-size: 1em; color: var(--primary-text-color); white-space: nowrap;
        }
        .hdr {
          min-height: 0; border-top: none; padding: 0 0 4px;
          font-size: 0.8em; font-weight: 600; color: var(--secondary-text-color);
        }
        .linecell { gap: 6px; }
        .mode { --mdc-icon-size: 22px; flex: none; }
        .badge {
          font-weight: 700; font-size: 0.85em;
          min-width: 30px; text-align: center; padding: 2px 7px; border-radius: 4px;
          white-space: nowrap;
        }
        .badge.sbahn { background: #fff; color: #000; border: 1.5px solid #b0b0b0; }
        .badge.ir { background: #eb0000; color: #fff; font-style: italic; }
        .zeit { font-weight: 600; }
        .cd { color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
        .to { min-width: 0; overflow: hidden; }
        .totxt { max-width: 168px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .platform { font-weight: 700; }
        .platform.chg { color: var(--warning-color, #f9a825); }
        .hint { color: var(--error-color, #c62828); font-weight: 600; font-size: 0.9em; }
        .empty { padding: 14px 0; color: var(--secondary-text-color); text-align: center; }
      </style>
      <ha-card>
        <div class="wrap">
          ${this._config.show_clock === false ? "" : `<div class="clockbar">
            <span class="date">${this._escape(now.date)}</span>
            <span class="time">${this._escape(now.time)}</span>
          </div>`}
          <div class="head">
            <div class="headrow">
              <div class="title">${this._escape(title)}</div>
              ${this._config.show_type === false ? "" : `<div class="typelabel">${TYPE_DEPARTURES[lang] || TYPE_DEPARTURES.en}</div>`}
            </div>
            ${address ? `<div class="addr">${this._escape(address)}</div>` : ""}
          </div>
          ${rows ? `<div class="board" style="grid-template-columns:${cols};">${header}${rows}</div>` : `<div class="empty">${NO_DEP_WORD[lang] || NO_DEP_WORD.en}</div>`}
        </div>
      </ha-card>`;
  }

  _escape(s) {
    const div = document.createElement("div");
    div.textContent = s == null ? "" : String(s);
    return div.innerHTML;
  }
}

customElements.define("swiss-transport-card", SwissTransportCard);

const EDITOR_LABELS = {
  entity: { de: "Sensor", en: "Sensor", fr: "Capteur", it: "Sensore" },
  title: { de: "Titel (optional)", en: "Title (optional)", fr: "Titre (optionnel)", it: "Titolo (opzionale)" },
  rows: { de: "Maximale Zeilen", en: "Max rows", fr: "Lignes max.", it: "Righe max." },
  show_clock: { de: "Datum & Uhrzeit anzeigen", en: "Show date & time", fr: "Afficher date & heure", it: "Mostra data e ora" },
  show_type: { de: "Typ-Label anzeigen", en: "Show type label", fr: "Afficher le libellé de type", it: "Mostra etichetta tipo" },
};

class SwissTransportCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.addEventListener("value-changed", (ev) => {
        ev.stopPropagation();
        const config = { type: "custom:swiss-transport-card", ...ev.detail.value };
        if (!config.title) delete config.title;
        if (!config.rows) delete config.rows;
        // Keep the config clean: only store the toggles when turned off.
        if (config.show_clock !== false) delete config.show_clock;
        if (config.show_type !== false) delete config.show_type;
        this.dispatchEvent(
          new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true })
        );
      });
      this.appendChild(this._form);
    }
    const lang = ((this._hass.language || "en").split("-")[0]);
    this._form.hass = this._hass;
    this._form.data = {
      entity: this._config.entity || "",
      title: this._config.title || "",
      rows: this._config.rows || 8,
      show_clock: this._config.show_clock !== false,
      show_type: this._config.show_type !== false,
    };
    this._form.schema = [
      { name: "entity", required: true, selector: { entity: { domain: "sensor", integration: "swiss_transport" } } },
      { name: "title", selector: { text: {} } },
      { name: "rows", selector: { number: { min: 1, max: 20, mode: "box" } } },
      { name: "show_clock", selector: { boolean: {} } },
      { name: "show_type", selector: { boolean: {} } },
    ];
    this._form.computeLabel = (schema) =>
      (EDITOR_LABELS[schema.name] && (EDITOR_LABELS[schema.name][lang] || EDITOR_LABELS[schema.name].en)) ||
      schema.name;
  }
}

customElements.define("swiss-transport-card-editor", SwissTransportCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "swiss-transport-card",
  name: "Swiss Transport Card",
  description: "A departure board for a Swiss public transport station.",
  preview: true,
});


/* ------------------------------------------------------------------ *
 * swiss-transport-connection-card — a board for a saved from -> to    *
 * route sensor: one row per upcoming connection with departure time,  *
 * countdown, the line(s), arrival, duration and transfers, and delay. *
 * ------------------------------------------------------------------ */

const C_HDR_DEP = { de: "Ab", en: "Dep", fr: "Dép", it: "Part" };
const C_HDR_IN = HDR_IN;
const C_HDR_LINE = { de: "Linie", en: "Line", fr: "Ligne", it: "Linea" };
const C_HDR_ARR = { de: "An", en: "Arr", fr: "Arr", it: "Arr" };
const C_HDR_DUR = { de: "Dauer", en: "Duration", fr: "Durée", it: "Durata" };
const XFER_WORD = { de: "Umst.", en: "chg.", fr: "corr.", it: "camb." };

function connProductClass(label) {
  const c = (String(label).split(/\s+/)[0] || "").toUpperCase();
  return productClass(c);
}

class SwissTransportConnectionCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error("swiss-transport-connection-card: 'entity' is required");
    this._config = config;
    if (!this._root) this._root = this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  connectedCallback() {
    this._timer = setInterval(() => this._render(), 30000);
  }

  disconnectedCallback() {
    if (this._timer) clearInterval(this._timer);
  }

  static getConfigElement() {
    return document.createElement("swiss-transport-connection-card-editor");
  }

  static getStubConfig(hass, entities) {
    const e = (entities || []).find((x) => x.startsWith("sensor.swiss_transport_"));
    return { entity: e || "" };
  }

  getCardSize() {
    return 2 + Math.min((this._connections() || []).length || 3, this._maxRows());
  }

  _lang() {
    const l = ((this._hass && this._hass.language) || LANG_FALLBACK).split("-")[0];
    return ["de", "en", "fr", "it"].includes(l) ? l : LANG_FALLBACK;
  }

  _maxRows() {
    const n = parseInt(this._config.rows, 10);
    return Number.isFinite(n) && n > 0 ? n : 8;
  }

  _connections() {
    const st = this._hass && this._hass.states[this._config.entity];
    const c = st && st.attributes && st.attributes.connections;
    return Array.isArray(c) ? c : [];
  }

  _render() {
    if (!this._hass || !this._config) return;
    const lang = this._lang();
    const st = this._hass.states[this._config.entity];
    const attrs = (st && st.attributes) || {};
    const title =
      this._config.title ||
      (attrs.from_name && attrs.to_name ? `${attrs.from_name} → ${attrs.to_name}` : attrs.friendly_name || "");
    const cons = this._connections().slice(0, this._maxRows());
    const nowMs = Date.now();
    const now = nowParts(lang);

    const header = `
      <div class="cell hdr">${C_HDR_DEP[lang] || C_HDR_DEP.en}</div>
      <div class="cell hdr">${C_HDR_IN[lang] || C_HDR_IN.en}</div>
      <div class="cell hdr">${C_HDR_LINE[lang] || C_HDR_LINE.en}</div>
      <div class="cell hdr">${C_HDR_ARR[lang] || C_HDR_ARR.en}</div>
      <div class="cell hdr">${C_HDR_DUR[lang] || C_HDR_DUR.en}</div>`;

    const rows = cons
      .map((c) => {
        const delay = Number.isFinite(c.delay) ? c.delay : null;
        const depStr = c.departure ? String(c.departure).substr(11, 5) : "";
        const arrStr = c.arrival ? String(c.arrival).substr(11, 5) : "";
        const depMs = (c.departure_ts || 0) * 1000 + (delay ? delay * 60000 : 0);
        const minsLeft = Math.round((depMs - nowMs) / 60000);
        const countdown = minsLeft <= 0 ? (NOW_WORD[lang] || NOW_WORD.en) : `${minsLeft}′`;
        const delayStr = delay && delay > 0 ? ` <span class="delay">+${delay}</span>` : "";
        const badges = (c.products || [])
          .map((p) => {
            const cls = connProductClass(p);
            const style = cls === "other" ? "background:#455a64;color:#fff;" : "";
            return `<span class="badge ${cls}" style="${style}">${this._escape(p)}</span>`;
          })
          .join(" ");
        const dur = Number.isFinite(c.duration_min)
          ? (c.duration_min >= 60
              ? `${Math.floor(c.duration_min / 60)}h${String(c.duration_min % 60).padStart(2, "0")}`
              : `${c.duration_min} min`)
          : "";
        const xfer = Number.isFinite(c.transfers) && c.transfers > 0
          ? ` · ${c.transfers} ${XFER_WORD[lang] || XFER_WORD.en}`
          : "";
        return `
          <div class="cell dep">${this._escape(depStr)}${delayStr}</div>
          <div class="cell cd">${this._escape(countdown)}</div>
          <div class="cell lines">${badges}</div>
          <div class="cell arr">${this._escape(arrStr)}</div>
          <div class="cell dur">${this._escape(dur)}${xfer}</div>`;
      })
      .join("");

    this._root.innerHTML = `
      <style>
        .wrap { padding: 10px 14px 12px; }
        ${HEAD_CSS}
        .headrow { margin-bottom: 8px; }
        .title {
          font-size: 1.15em; font-weight: 500;
          color: var(--primary-text-color);
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .board {
          display: grid;
          grid-template-columns: auto auto 1fr auto auto;
          column-gap: 14px; align-items: center;
        }
        .cell {
          display: flex; align-items: center; min-height: 32px; gap: 4px;
          padding: 4px 0; white-space: nowrap;
          border-top: 1px solid var(--divider-color, rgba(127,127,127,.2));
          color: var(--primary-text-color);
        }
        .hdr {
          min-height: 0; border-top: none; padding: 0 0 4px;
          font-size: 0.8em; font-weight: 600; color: var(--secondary-text-color);
        }
        .dep, .arr { font-weight: 600; font-variant-numeric: tabular-nums; }
        .cd { color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
        .dur { font-size: 0.85em; color: var(--secondary-text-color); }
        .lines { min-width: 0; flex-wrap: wrap; }
        .delay { color: var(--error-color, #c62828); font-weight: 600; font-size: 0.85em; }
        .badge {
          font-weight: 700; font-size: 0.8em; padding: 1px 6px; border-radius: 4px; white-space: nowrap;
        }
        .badge.sbahn { background: #fff; color: #000; border: 1.5px solid #b0b0b0; }
        .badge.ir { background: #eb0000; color: #fff; font-style: italic; }
        .empty { padding: 14px 0; color: var(--secondary-text-color); text-align: center; }
      </style>
      <ha-card>
        <div class="wrap">
          ${this._config.show_clock === false ? "" : `<div class="clockbar">
            <span class="date">${this._escape(now.date)}</span>
            <span class="time">${this._escape(now.time)}</span>
          </div>`}
          <div class="headrow">
            <div class="title">${this._escape(title)}</div>
            ${this._config.show_type === false ? "" : `<div class="typelabel">${TYPE_CONNECTION[lang] || TYPE_CONNECTION.en}</div>`}
          </div>
          ${rows ? `<div class="board">${header}${rows}</div>` : `<div class="empty">${NO_DEP_WORD[lang] || NO_DEP_WORD.en}</div>`}
        </div>
      </ha-card>`;
  }

  _escape(s) {
    const div = document.createElement("div");
    div.textContent = s == null ? "" : String(s);
    return div.innerHTML;
  }
}

customElements.define("swiss-transport-connection-card", SwissTransportConnectionCard);

class SwissTransportConnectionCardEditor extends HTMLElement {
  setConfig(config) { this._config = config; this._render(); }
  set hass(hass) { this._hass = hass; this._render(); }
  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.addEventListener("value-changed", (ev) => {
        ev.stopPropagation();
        const config = { type: "custom:swiss-transport-connection-card", ...ev.detail.value };
        if (!config.title) delete config.title;
        if (!config.rows) delete config.rows;
        if (config.show_clock !== false) delete config.show_clock;
        if (config.show_type !== false) delete config.show_type;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    const lang = ((this._hass.language || "en").split("-")[0]);
    this._form.hass = this._hass;
    this._form.data = {
      entity: this._config.entity || "",
      title: this._config.title || "",
      rows: this._config.rows || 8,
      show_clock: this._config.show_clock !== false,
      show_type: this._config.show_type !== false,
    };
    this._form.schema = [
      { name: "entity", required: true, selector: { entity: { domain: "sensor", integration: "swiss_transport" } } },
      { name: "title", selector: { text: {} } },
      { name: "rows", selector: { number: { min: 1, max: 12, mode: "box" } } },
      { name: "show_clock", selector: { boolean: {} } },
      { name: "show_type", selector: { boolean: {} } },
    ];
    this._form.computeLabel = (schema) =>
      (EDITOR_LABELS[schema.name] && (EDITOR_LABELS[schema.name][lang] || EDITOR_LABELS[schema.name].en)) || schema.name;
  }
}

customElements.define("swiss-transport-connection-card-editor", SwissTransportConnectionCardEditor);

window.customCards.push({
  type: "swiss-transport-connection-card",
  name: "Swiss Transport Connection Card",
  description: "A board of connections for a saved from to route.",
  preview: true,
});
