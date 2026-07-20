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
// Arrival boards: the API returns the journey's origin in the same field, so
// only the column header changes (Nach → Von), mirroring real arrival boards.
const HDR_FROM = { de: "Von", en: "From", fr: "Provenance", it: "Provenienza" };
const HDR_PLATFORM = { de: "Gleis", en: "Platform", fr: "Voie", it: "Binario" };
const HDR_OCC = { de: "Ausl.", en: "Occ.", fr: "Occ.", it: "Occ." };
const HDR_INFO = { de: "Hinweis", en: "Info", fr: "Info", it: "Info" };
const NOW_WORD = { de: "jetzt", en: "now", fr: "maint.", it: "ora" };
const CANCELLED_WORD = { de: "Ausfall", en: "Cancelled", fr: "Supprimé", it: "Soppresso" };
const MORE_ALERTS = { de: "+{n} weitere", en: "+{n} more", fr: "+{n} de plus", it: "+{n} altre" };

// Occupancy (from OJP): coarse 1 (low) .. 3 (high), shown as a small icon.
const OCC_ICON = { 1: "mdi:account", 2: "mdi:account-multiple", 3: "mdi:account-group" };
const OCC_COLOR = { 1: "#2e7d32", 2: "#f9a825", 3: "#c62828" };
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
const TYPE_ARRIVALS = { de: "Ankünfte", en: "Arrivals", fr: "Arrivées", it: "Arrivi" };
const NO_ARR_WORD = { de: "Keine Ankünfte", en: "No arrivals", fr: "Aucune arrivée", it: "Nessun arrivo" };
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

// Labels for the "timetable mode" banner shown when a card is following the
// global date/time selection rather than the live board.
const TT_TIMETABLE = { de: "Fahrplan", en: "Timetable", fr: "Horaire", it: "Orario" };
const TT_DEPART = { de: "Abfahrt", en: "Departure", fr: "Départ", it: "Partenza" };
const TT_ARRIVE = { de: "Ankunft", en: "Arrival", fr: "Arrivée", it: "Arrivo" };

const API_BASE = "https://transport.opendata.ch/v1";

/* Selected instant (from a datetime entity's state) → local date/time parts
 * the API expects. Uses the browser's local timezone. */
function fmtSelected(state) {
  const dt = new Date(state);
  if (isNaN(dt.getTime())) return null;
  const p = (n) => String(n).padStart(2, "0");
  const date = `${dt.getFullYear()}-${p(dt.getMonth() + 1)}-${p(dt.getDate())}`;
  const time = `${p(dt.getHours())}:${p(dt.getMinutes())}`;
  return { date, time, datetime: `${date} ${time}`, dateObj: dt };
}

/* Flatten one stationboard entry (mirrors the coordinator's _parse_departure).
 * The API keeps the board time in the departure fields for both departure and
 * arrival boards (arrival timestamps come back null), so we always read those;
 * `type=arrival` already selects the right set of trains. */
function parseBoardEntry(entry) {
  const stop = entry.stop || {};
  const ts = stop.departureTimestamp;
  if (!ts) return null;
  const category = (entry.category || "").trim();
  const number = (entry.number || "").trim();
  const isDigit = /^\d+$/.test(number);
  let line;
  if (["B", "T", "BUS", "TRM", "NFB", "NFT"].includes(category) && number) line = number;
  else if (category && number && !isDigit) line = `${category}${number}`;
  else line = category || number || "?";
  return {
    line,
    category,
    number,
    to: entry.to,
    departure: stop.departure,
    departure_ts: parseInt(ts, 10),
    delay: typeof stop.delay === "number" ? stop.delay : null,
    platform: stop.platform,
    platform_changed: false,
  };
}

function durationToMinutes(value) {
  try {
    const [d, rest] = String(value).split("d");
    const [h, m] = rest.split(":");
    return parseInt(d, 10) * 1440 + parseInt(h, 10) * 60 + parseInt(m, 10);
  } catch (e) {
    return null;
  }
}

/* Mirrors the coordinator's _parse_connection (incl. legs/changes). */
function parseConnectionEntry(con) {
  const frm = con.from || {};
  const to = con.to || {};
  if (!frm.departureTimestamp) return null;
  const legs = [];
  for (const sec of con.sections || []) {
    const j = sec.journey;
    if (!j) continue;
    const cat = (j.category || "").trim();
    const num = (j.number || "").trim();
    const isDigit = /^\d+$/.test(num);
    const line = num && !isDigit ? `${cat}${num}` : cat || num || "";
    const sd = sec.departure || {};
    const sa = sec.arrival || {};
    legs.push({
      line,
      from_name: (sd.station || {}).name,
      from_platform: sd.platform,
      to_name: (sa.station || {}).name,
      to_platform: sa.platform,
    });
  }
  const changes = [];
  for (let i = 0; i < legs.length - 1; i++) {
    changes.push({
      station: legs[i].to_name,
      arr_platform: legs[i].to_platform,
      dep_platform: legs[i + 1].from_platform,
    });
  }
  return {
    departure: frm.departure,
    departure_ts: parseInt(frm.departureTimestamp, 10),
    dep_platform: frm.platform,
    delay: typeof frm.delay === "number" ? frm.delay : null,
    arrival: to.arrival,
    arrival_ts: to.arrivalTimestamp ? parseInt(to.arrivalTimestamp, 10) : null,
    arr_platform: to.platform,
    duration_min: durationToMinutes(con.duration),
    transfers: con.transfers,
    products: con.products || [],
    changes,
  };
}

async function fetchBoard(stationId, limit, datetime, arrival) {
  const p = new URLSearchParams({ id: stationId, limit: String(limit) });
  if (datetime) p.set("datetime", datetime);
  if (arrival) p.set("type", "arrival");
  const resp = await fetch(`${API_BASE}/stationboard?${p.toString()}`);
  const data = await resp.json();
  return (data.stationboard || [])
    .map((e) => parseBoardEntry(e))
    .filter((x) => x)
    .sort((a, b) => a.departure_ts - b.departure_ts);
}

async function fetchConnections(fromId, toId, limit, date, time, isArrival) {
  const p = new URLSearchParams({ from: fromId, to: toId, limit: String(limit) });
  if (date) p.set("date", date);
  if (time) p.set("time", time);
  if (isArrival) p.set("isArrivalTime", "1");
  const resp = await fetch(`${API_BASE}/connections?${p.toString()}`);
  const data = await resp.json();
  return (data.connections || [])
    .map(parseConnectionEntry)
    .filter((x) => x)
    .sort((a, b) => a.departure_ts - b.departure_ts);
}

/* Timetable-mode banner ("Fahrplan: Di 21.07. 08:00 · Abfahrt"). */
function timetableBanner(sel, mode, lang, escape) {
  const loc = LOCALE[lang] || "de-CH";
  const when = sel.dateObj.toLocaleString(loc, {
    weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
  const kind = mode === "arrive" ? TT_ARRIVE[lang] || TT_ARRIVE.en : TT_DEPART[lang] || TT_DEPART.en;
  return `<div class="ttbar"><ha-icon icon="mdi:clock-outline"></ha-icon><span>${
    TT_TIMETABLE[lang] || TT_TIMETABLE.en
  }: ${escape(when)} · ${escape(kind)}</span></div>`;
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
    this._maybeFetch();
    this._render();
  }

  connectedCallback() {
    // Keep the clock and countdown fresh even when no state changes arrive.
    this._timer = setInterval(() => this._render(), 30000);
  }

  _mode() {
    const e = this._config.mode_entity && this._hass && this._hass.states[this._config.mode_entity];
    return (e && e.state) || "live";
  }

  _selTime() {
    const e = this._config.datetime_entity && this._hass && this._hass.states[this._config.datetime_entity];
    if (!e || ["unknown", "unavailable", ""].includes(e.state)) return null;
    return fmtSelected(e.state);
  }

  // Fetch the timetable for the selected moment when not in live mode. Keyed so
  // it only re-fetches when the query actually changes.
  _maybeFetch() {
    const mode = this._mode();
    const sel = this._selTime();
    if (mode === "live" || !sel) {
      this._sig = null;
      this._fetched = null;
      return;
    }
    const st = this._hass.states[this._config.entity];
    const stationId = st && st.attributes && st.attributes.station_id;
    if (!stationId) return;
    const arrival = mode === "arrive";
    const sig = `${stationId}|${sel.datetime}|${arrival}|${this._maxRows()}`;
    if (sig === this._sig) return;
    this._sig = sig;
    fetchBoard(stationId, this._maxRows(), sel.datetime, arrival)
      .then((list) => {
        if (this._sig === sig) {
          this._fetched = list;
          this._render();
        }
      })
      .catch(() => {
        if (this._sig === sig) {
          this._fetched = [];
          this._render();
        }
      });
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
    // In timetable mode show the client-fetched board; otherwise the live one.
    if (this._mode() !== "live" && this._selTime() && Array.isArray(this._fetched)) {
      return this._fetched;
    }
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
    const attrs = (st && st.attributes) || {};
    const now = nowParts(lang);
    const deps = this._departures().slice(0, this._maxRows());
    const nowMs = Date.now();
    // Hide the platform column entirely when not a single departure has one
    // (bus/tram stops). The destination column flexes to fill the card, so
    // nothing overflows regardless.
    const anyPlatform = deps.some((d) => d.platform);
    // Occupancy column only appears when the (optional) OJP real-time source
    // actually supplied occupancy for at least one departure.
    const anyOcc =
      this._config.show_occupancy !== false &&
      deps.some((d) => Number.isFinite(d.occupancy) && d.occupancy > 0);
    // minmax(0, 1fr) lets the destination shrink (with ellipsis) so the board
    // never overflows the card at any width/zoom.
    const col = ["auto", "auto", "auto", "minmax(0, 1fr)"];
    if (anyPlatform) col.push("auto");
    if (anyOcc) col.push("auto");
    col.push("auto"); // hint
    const cols = col.join(" ");

    // In arrival view the direction column shows where the service comes from.
    const arrView = this._mode() === "arrive" && !!this._selTime();
    const hdrDir = arrView ? HDR_FROM[lang] || HDR_FROM.en : HDR_TO[lang] || HDR_TO.en;
    const header = `
      <div class="cell hdr"></div>
      <div class="cell hdr">${HDR_TIME[lang] || HDR_TIME.en}</div>
      <div class="cell hdr">${HDR_IN[lang] || HDR_IN.en}</div>
      <div class="cell hdr">${hdrDir}</div>
      ${anyPlatform ? `<div class="cell hdr">${HDR_PLATFORM[lang] || HDR_PLATFORM.en}</div>` : ""}
      ${anyOcc ? `<div class="cell hdr occ">${HDR_OCC[lang] || HDR_OCC.en}</div>` : ""}
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
        const cancelled = !!d.cancelled;
        const delay = Number.isFinite(d.delay) ? d.delay : null;
        const timeStr = d.departure ? String(d.departure).substr(11, 5) : "";
        // Countdown to the real (delay-adjusted) departure.
        const depMs = (d.departure_ts || 0) * 1000 + (delay ? delay * 60000 : 0);
        const minsLeft = Math.round((depMs - nowMs) / 60000);
        const countdown = cancelled
          ? ""
          : minsLeft <= 0
            ? (NOW_WORD[lang] || NOW_WORD.en)
            : `${minsLeft}′`;
        // Hint column: cancellation takes precedence, then a delay. Both are
        // controlled text, safe as HTML. Station-wide disruptions are shown in
        // the banner above rather than marking every row.
        let hintHtml = "";
        if (cancelled) {
          hintHtml = `<span class="cxl">${CANCELLED_WORD[lang] || CANCELLED_WORD.en}</span>`;
        } else if (delay && delay > 0) {
          hintHtml = this._escape((LATE_FMT[lang] || LATE_FMT.en).replace("{n}", delay));
        }
        const occCell = anyOcc
          ? `<div class="cell occ">${
              Number.isFinite(d.occupancy) && d.occupancy > 0
                ? `<ha-icon icon="${OCC_ICON[d.occupancy]}" style="color:${OCC_COLOR[d.occupancy]};--mdc-icon-size:20px;"></ha-icon>`
                : ""
            }</div>`
          : "";
        return `
          <div class="cell linecell">
            <ha-icon class="mode" icon="${MODE_ICON[m]}" style="color:${MODE_COLOR[m]};"></ha-icon>
            <div class="badge ${pcls}" style="${badgeStyle}">${this._escape(badgeText)}</div>
          </div>
          <div class="cell zeit${cancelled ? " cancelled" : ""}">${this._escape(timeStr)}</div>
          <div class="cell cd">${this._escape(countdown)}</div>
          <div class="cell to"><span class="totxt">${this._escape(d.to || "")}</span></div>
          ${anyPlatform ? `<div class="cell platform${d.platform_changed ? " chg" : ""}">${this._escape(d.platform || "")}</div>` : ""}
          ${occCell}
          <div class="cell hint">${hintHtml}</div>`;
      })
      .join("");

    // Station-wide disruption messages (OJP only), shown as a banner above the
    // board. Toggleable via the visual editor.
    // Timetable mode: card is following the global date/time selection.
    const selTime = this._selTime();
    const ttMode = this._mode() !== "live" && selTime;
    const arrivalView = ttMode && this._mode() === "arrive";
    const ttHtml = ttMode ? timetableBanner(selTime, this._mode(), lang, (s) => this._escape(s)) : "";
    const typeLabel = arrivalView ? TYPE_ARRIVALS : TYPE_DEPARTURES;
    const emptyWord = arrivalView ? NO_ARR_WORD : NO_DEP_WORD;

    // Disruption messages are live-only; hide them in timetable mode.
    const alerts = !ttMode && Array.isArray(attrs.alerts) ? attrs.alerts : [];
    // How many disruption messages to show; 0 (or negative) means all.
    const maxAlertsCfg = parseInt(this._config.max_alerts, 10);
    const maxAlerts = Number.isFinite(maxAlertsCfg) ? maxAlertsCfg : 3;
    const alertsShown = maxAlerts <= 0 ? alerts : alerts.slice(0, maxAlerts);
    const alertsMore = alerts.length - alertsShown.length;
    const alertsHtml =
      this._config.show_alerts !== false && alerts.length
        ? `<div class="alerts">${alertsShown
            .map((a) => `<div class="alert"><ha-icon icon="mdi:alert"></ha-icon><span>${this._escape(a)}</span></div>`)
            .join("")}${
            alertsMore > 0
              ? `<div class="alert-more">${this._escape((MORE_ALERTS[lang] || MORE_ALERTS.en).replace("{n}", alertsMore))}</div>`
              : ""
          }</div>`
        : "";

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
        .occ { justify-content: center; }
        .hint { color: var(--error-color, #c62828); font-weight: 600; font-size: 0.9em; }
        .hint .cxl { color: var(--error-color, #c62828); font-weight: 700; }
        .zeit.cancelled { text-decoration: line-through; color: var(--secondary-text-color); font-weight: 500; }
        .alerts { display: flex; flex-direction: column; gap: 4px; margin: 2px 0 10px; }
        .alert {
          display: flex; gap: 6px; align-items: flex-start; white-space: normal;
          font-size: 0.85em; color: var(--primary-text-color);
          background: rgba(249, 168, 37, 0.12);
          border-left: 3px solid var(--warning-color, #f9a825);
          padding: 5px 8px; border-radius: 4px;
        }
        .alert ha-icon { --mdc-icon-size: 18px; color: var(--warning-color, #f9a825); flex: none; }
        .alert-more { font-size: 0.8em; color: var(--secondary-text-color); padding: 0 8px; }
        .ttbar {
          display: flex; gap: 6px; align-items: center; margin: 2px 0 10px;
          font-size: 0.85em; font-weight: 600; color: var(--primary-text-color);
          background: rgba(41, 121, 255, 0.12);
          border-left: 3px solid var(--info-color, #2979ff);
          padding: 5px 8px; border-radius: 4px;
        }
        .ttbar ha-icon { --mdc-icon-size: 18px; color: var(--info-color, #2979ff); flex: none; }
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
              ${this._config.show_type === false ? "" : `<div class="typelabel">${typeLabel[lang] || typeLabel.en}</div>`}
            </div>
            ${address ? `<div class="addr">${this._escape(address)}</div>` : ""}
          </div>
          ${ttHtml}
          ${alertsHtml}
          ${rows ? `<div class="board" style="grid-template-columns:${cols};">${header}${rows}</div>` : `<div class="empty">${emptyWord[lang] || emptyWord.en}</div>`}
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
  show_occupancy: { de: "Auslastung anzeigen", en: "Show occupancy", fr: "Afficher l'occupation", it: "Mostra occupazione" },
  show_alerts: { de: "Störungsmeldungen anzeigen", en: "Show disruptions", fr: "Afficher les perturbations", it: "Mostra perturbazioni" },
  max_alerts: { de: "Max. Störungsmeldungen (0 = alle)", en: "Max disruptions (0 = all)", fr: "Perturbations max. (0 = toutes)", it: "Perturbazioni max. (0 = tutte)" },
  show_changes: { de: "Umsteigepunkte anzeigen", en: "Show transfers", fr: "Afficher les changements", it: "Mostra cambi" },
  datetime_entity: { de: "Datum/Zeit-Entität (optional)", en: "Date/time entity (optional)", fr: "Entité date/heure (opt.)", it: "Entità data/ora (opz.)" },
  mode_entity: { de: "Modus-Entität (optional)", en: "Mode entity (optional)", fr: "Entité mode (opt.)", it: "Entità modalità (opz.)" },
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
        if (config.show_occupancy !== false) delete config.show_occupancy;
        if (config.show_alerts !== false) delete config.show_alerts;
        // Default is 3; only persist when the user chose something else.
        if (config.max_alerts === "" || config.max_alerts === null || config.max_alerts === 3) delete config.max_alerts;
        if (!config.datetime_entity) delete config.datetime_entity;
        if (!config.mode_entity) delete config.mode_entity;
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
      show_occupancy: this._config.show_occupancy !== false,
      show_alerts: this._config.show_alerts !== false,
      max_alerts: Number.isFinite(parseInt(this._config.max_alerts, 10)) ? parseInt(this._config.max_alerts, 10) : 3,
      datetime_entity: this._config.datetime_entity || "",
      mode_entity: this._config.mode_entity || "",
    };
    this._form.schema = [
      { name: "entity", required: true, selector: { entity: { domain: "sensor", integration: "swiss_transport" } } },
      { name: "title", selector: { text: {} } },
      { name: "rows", selector: { number: { min: 1, max: 20, mode: "box" } } },
      { name: "show_clock", selector: { boolean: {} } },
      { name: "show_type", selector: { boolean: {} } },
      { name: "show_occupancy", selector: { boolean: {} } },
      { name: "show_alerts", selector: { boolean: {} } },
      { name: "max_alerts", selector: { number: { min: 0, max: 20, mode: "box" } } },
      { name: "datetime_entity", selector: { entity: { domain: "datetime" } } },
      { name: "mode_entity", selector: { entity: { domain: "select" } } },
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
const PF_ABBR = { de: "Gl.", en: "Pl.", fr: "V.", it: "Bin." };
const CHANGE_WORD = { de: "Umsteigen", en: "Change", fr: "Changement", it: "Cambio" };

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
    this._maybeFetch();
    this._render();
  }

  connectedCallback() {
    this._timer = setInterval(() => this._render(), 30000);
  }

  disconnectedCallback() {
    if (this._timer) clearInterval(this._timer);
  }

  _mode() {
    const e = this._config.mode_entity && this._hass && this._hass.states[this._config.mode_entity];
    return (e && e.state) || "live";
  }

  _selTime() {
    const e = this._config.datetime_entity && this._hass && this._hass.states[this._config.datetime_entity];
    if (!e || ["unknown", "unavailable", ""].includes(e.state)) return null;
    return fmtSelected(e.state);
  }

  _maybeFetch() {
    const mode = this._mode();
    const sel = this._selTime();
    if (mode === "live" || !sel) {
      this._sig = null;
      this._fetched = null;
      return;
    }
    const st = this._hass.states[this._config.entity];
    const a = (st && st.attributes) || {};
    if (!a.from_id || !a.to_id) return;
    const isArrival = mode === "arrive";
    const sig = `${a.from_id}|${a.to_id}|${sel.datetime}|${isArrival}|${this._maxRows()}`;
    if (sig === this._sig) return;
    this._sig = sig;
    fetchConnections(a.from_id, a.to_id, this._maxRows(), sel.date, sel.time, isArrival)
      .then((list) => {
        if (this._sig === sig) {
          this._fetched = list;
          this._render();
        }
      })
      .catch(() => {
        if (this._sig === sig) {
          this._fetched = [];
          this._render();
        }
      });
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
    if (this._mode() !== "live" && this._selTime() && Array.isArray(this._fetched)) {
      return this._fetched;
    }
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
    const selTime = this._selTime();
    const ttMode = this._mode() !== "live" && selTime;
    const ttHtml = ttMode ? timetableBanner(selTime, this._mode(), lang, (s) => this._escape(s)) : "";

    // Platform columns (Gleis) for departure and arrival, shown like on the
    // departure board — and dropped when no connection has that platform.
    const anyDepPf = cons.some((c) => c.dep_platform);
    const anyArrPf = cons.some((c) => c.arr_platform);
    const ccol = ["auto"]; // Ab
    if (anyDepPf) ccol.push("auto"); // Gleis (ab)
    ccol.push("auto"); // in
    ccol.push("1fr"); // Linie
    ccol.push("auto"); // An
    if (anyArrPf) ccol.push("auto"); // Gleis (an)
    ccol.push("auto"); // Dauer
    const cCols = ccol.join(" ");
    const pfHdr = HDR_PLATFORM[lang] || HDR_PLATFORM.en;

    const header = `
      <div class="cell hdr">${C_HDR_DEP[lang] || C_HDR_DEP.en}</div>
      ${anyDepPf ? `<div class="cell hdr">${pfHdr}</div>` : ""}
      <div class="cell hdr">${C_HDR_IN[lang] || C_HDR_IN.en}</div>
      <div class="cell hdr">${C_HDR_LINE[lang] || C_HDR_LINE.en}</div>
      <div class="cell hdr">${C_HDR_ARR[lang] || C_HDR_ARR.en}</div>
      ${anyArrPf ? `<div class="cell hdr">${pfHdr}</div>` : ""}
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
        const pf = PF_ABBR[lang] || PF_ABBR.en;
        // Transfer points: where to change, with arrival → onward platform.
        const changes = Array.isArray(c.changes) ? c.changes : [];
        const changesHtml =
          this._config.show_changes !== false && changes.length
            ? `<div class="changes"><ha-icon icon="mdi:transit-transfer"></ha-icon><span>${
                CHANGE_WORD[lang] || CHANGE_WORD.en
              }: ${changes
                .map((ch) => {
                  const st = this._escape(ch.station || "");
                  const pfs =
                    ch.arr_platform || ch.dep_platform
                      ? ` (${pf} ${this._escape(ch.arr_platform || "?")} → ${this._escape(ch.dep_platform || "?")})`
                      : "";
                  return st + pfs;
                })
                .join(", ")}</span></div>`
            : "";
        return `
          <div class="cell dep">${this._escape(depStr)}${delayStr}</div>
          ${anyDepPf ? `<div class="cell platform">${this._escape(c.dep_platform || "")}</div>` : ""}
          <div class="cell cd">${this._escape(countdown)}</div>
          <div class="cell lines">${badges}</div>
          <div class="cell arr">${this._escape(arrStr)}</div>
          ${anyArrPf ? `<div class="cell platform">${this._escape(c.arr_platform || "")}</div>` : ""}
          <div class="cell dur">${this._escape(dur)}${xfer}</div>
          ${changesHtml}`;
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
          /* grid-template-columns is set inline: Ab · [Gleis] · in · Linie ·
           * An · [Gleis] · Dauer — platform columns dropped when unavailable. */
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
        .dep, .arr { font-weight: 600; font-variant-numeric: tabular-nums; gap: 4px; }
        .cd { color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
        .dur { font-size: 0.85em; color: var(--secondary-text-color); }
        .lines { min-width: 0; flex-wrap: wrap; }
        .delay { color: var(--error-color, #c62828); font-weight: 600; font-size: 0.85em; }
        .platform { font-weight: 700; }
        .changes {
          grid-column: 1 / -1; display: flex; gap: 6px; align-items: center;
          font-size: 0.8em; color: var(--secondary-text-color);
          padding: 0 0 6px; white-space: normal;
        }
        .changes ha-icon { --mdc-icon-size: 16px; color: var(--secondary-text-color); flex: none; }
        .badge {
          font-weight: 700; font-size: 0.8em; padding: 1px 6px; border-radius: 4px; white-space: nowrap;
        }
        .badge.sbahn { background: #fff; color: #000; border: 1.5px solid #b0b0b0; }
        .badge.ir { background: #eb0000; color: #fff; font-style: italic; }
        .ttbar {
          display: flex; gap: 6px; align-items: center; margin: 2px 0 10px;
          font-size: 0.85em; font-weight: 600; color: var(--primary-text-color);
          background: rgba(41, 121, 255, 0.12);
          border-left: 3px solid var(--info-color, #2979ff);
          padding: 5px 8px; border-radius: 4px;
        }
        .ttbar ha-icon { --mdc-icon-size: 18px; color: var(--info-color, #2979ff); flex: none; }
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
          ${ttHtml}
          ${rows ? `<div class="board" style="grid-template-columns:${cCols};">${header}${rows}</div>` : `<div class="empty">${NO_DEP_WORD[lang] || NO_DEP_WORD.en}</div>`}
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
        if (config.show_changes !== false) delete config.show_changes;
        if (!config.datetime_entity) delete config.datetime_entity;
        if (!config.mode_entity) delete config.mode_entity;
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
      show_changes: this._config.show_changes !== false,
      datetime_entity: this._config.datetime_entity || "",
      mode_entity: this._config.mode_entity || "",
    };
    this._form.schema = [
      { name: "entity", required: true, selector: { entity: { domain: "sensor", integration: "swiss_transport" } } },
      { name: "title", selector: { text: {} } },
      { name: "rows", selector: { number: { min: 1, max: 12, mode: "box" } } },
      { name: "show_clock", selector: { boolean: {} } },
      { name: "show_type", selector: { boolean: {} } },
      { name: "show_changes", selector: { boolean: {} } },
      { name: "datetime_entity", selector: { entity: { domain: "datetime" } } },
      { name: "mode_entity", selector: { entity: { domain: "select" } } },
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


/* ------------------------------------------------------------------ *
 * swiss-transport-controls-card — the global date/time + mode selector *
 * bar. A compact segmented control (Live / Departure / Arrival) plus a  *
 * date/time picker with ‹ › stepping. Drives the shared datetime and    *
 * select entities that every board follows.                            *
 * ------------------------------------------------------------------ */

const CTRL_LIVE = { de: "Live", en: "Live", fr: "Live", it: "Live" };

class SwissTransportControlsCard extends HTMLElement {
  setConfig(config) {
    this._config = {
      time_entity: "datetime.swiss_transport_time",
      mode_entity: "select.swiss_transport_mode",
      ...config,
    };
    if (!this._root) this._root = this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  static getStubConfig() {
    return { time_entity: "datetime.swiss_transport_time", mode_entity: "select.swiss_transport_mode" };
  }

  getCardSize() {
    return 1;
  }

  _lang() {
    const l = ((this._hass && this._hass.language) || LANG_FALLBACK).split("-")[0];
    return ["de", "en", "fr", "it"].includes(l) ? l : LANG_FALLBACK;
  }

  _mode() {
    const e = this._hass.states[this._config.mode_entity];
    return (e && e.state) || "live";
  }

  _timeDate() {
    const e = this._hass.states[this._config.time_entity];
    const d = e && e.state ? new Date(e.state) : new Date();
    return isNaN(d.getTime()) ? new Date() : d;
  }

  _setMode(m) {
    this._hass.callService("select", "select_option", { entity_id: this._config.mode_entity, option: m });
  }

  _setTime(d) {
    const p = (n) => String(n).padStart(2, "0");
    const v = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:00`;
    this._hass.callService("datetime", "set_value", { entity_id: this._config.time_entity, datetime: v });
    if (this._mode() === "live") this._setMode("depart");
  }

  _step(min) {
    const d = this._timeDate();
    d.setMinutes(d.getMinutes() + min);
    this._setTime(d);
  }

  _render() {
    if (!this._hass || !this._config) return;
    // Don't clobber the picker while the user is interacting with it.
    if (this._root.activeElement && this._root.activeElement.tagName === "INPUT") return;
    const lang = this._lang();
    const mode = this._mode();
    const d = this._timeDate();
    const p = (n) => String(n).padStart(2, "0");
    const inputVal = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
    const pill = (m, txt) => `<button class="pill${mode === m ? " active" : ""}" data-m="${m}">${this._escape(txt)}</button>`;

    this._root.innerHTML = `
      <style>
        ha-card { padding: 8px 12px; }
        .bar { display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: center; justify-content: space-between; }
        .pills { display: inline-flex; background: var(--divider-color, rgba(127,127,127,.18)); border-radius: 999px; padding: 3px; }
        .pill {
          border: none; background: transparent; cursor: pointer;
          font: inherit; font-size: 0.9em; font-weight: 600;
          color: var(--secondary-text-color); padding: 5px 14px; border-radius: 999px;
        }
        .pill.active { background: var(--card-background-color, #fff); color: var(--primary-color); box-shadow: 0 1px 3px rgba(0,0,0,.2); }
        .timectl { display: inline-flex; align-items: center; gap: 4px; opacity: 1; transition: opacity .15s; }
        .timectl.off { opacity: .4; }
        .nav {
          border: none; background: transparent; cursor: pointer; color: var(--primary-text-color);
          display: inline-flex; align-items: center; border-radius: 50%; padding: 4px;
        }
        .nav:hover { background: var(--divider-color, rgba(127,127,127,.18)); }
        input[type="datetime-local"] {
          font: inherit; font-size: 0.95em; color: var(--primary-text-color);
          background: var(--divider-color, rgba(127,127,127,.14));
          border: none; border-radius: 8px; padding: 6px 10px; color-scheme: light dark;
        }
      </style>
      <ha-card>
        <div class="bar">
          <div class="pills">
            ${pill("live", CTRL_LIVE[lang] || "Live")}
            ${pill("depart", TT_DEPART[lang] || TT_DEPART.en)}
            ${pill("arrive", TT_ARRIVE[lang] || TT_ARRIVE.en)}
          </div>
          <div class="timectl ${mode === "live" ? "off" : ""}">
            <button class="nav" data-step="-30" title="-30 min"><ha-icon icon="mdi:chevron-left"></ha-icon></button>
            <input type="datetime-local" value="${inputVal}">
            <button class="nav" data-step="30" title="+30 min"><ha-icon icon="mdi:chevron-right"></ha-icon></button>
          </div>
        </div>
      </ha-card>`;

    this._root.querySelectorAll(".pill").forEach((b) => {
      b.onclick = () => this._setMode(b.dataset.m);
    });
    this._root.querySelectorAll(".nav").forEach((b) => {
      b.onclick = () => this._step(parseInt(b.dataset.step, 10));
    });
    const inp = this._root.querySelector("input");
    if (inp) {
      inp.onchange = () => {
        if (inp.value) this._setTime(new Date(inp.value));
      };
    }
  }

  _escape(s) {
    const div = document.createElement("div");
    div.textContent = s == null ? "" : String(s);
    return div.innerHTML;
  }
}

customElements.define("swiss-transport-controls-card", SwissTransportControlsCard);

window.customCards.push({
  type: "swiss-transport-controls-card",
  name: "Swiss Transport Controls",
  description: "Global date/time and mode selector that every Swiss Transport board follows.",
  preview: false,
});
