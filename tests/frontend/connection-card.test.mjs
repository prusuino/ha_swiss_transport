// Self-check for the connection card's board options — run:
//   node tests/frontend/connection-card.test.mjs
//
// The card renders in a browser, so this shims the few DOM pieces it touches
// and asserts on the generated markup. Covers `from`, `hide_departed`,
// `group_by_mode`, `show_arrival` and `stale_threshold`, and that a card
// without any of them renders as before.

import assert from "node:assert/strict";

const defined = {};
class ElementShim {
  attachShadow() {
    this.shadowRoot = { innerHTML: "", addEventListener() {} };
    return this.shadowRoot;
  }
}
globalThis.HTMLElement = ElementShim;
globalThis.customElements = { define: (name, cls) => (defined[name] = cls) };
globalThis.window = globalThis;
globalThis.setInterval = () => 0;
globalThis.clearInterval = () => {};
globalThis.fetch = () => Promise.reject(new Error("no network in tests"));
globalThis.getComputedStyle = () => ({ getPropertyValue: () => "" });
globalThis.document = {
  createElement: () => {
    const el = {
      set textContent(v) {
        el.html = String(v).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
      },
      get innerHTML() {
        return el.html;
      },
    };
    return el;
  },
};

await import("../../custom_components/swiss_transport/frontend/swiss-transport-card.js");
const Card = defined["swiss-transport-connection-card"];

const NOW = Date.now();
const conn = (min, { line = "S9", category = "S", from = "Aarau", delay = 0 } = {}) => ({
  departure: new Date(NOW + min * 60000).toISOString().replace("Z", "+0000"),
  departure_ts: Math.floor((NOW + min * 60000) / 1000),
  delay,
  dep_platform: "1",
  arrival: new Date(NOW + (min + 10) * 60000).toISOString().replace("Z", "+0000"),
  arr_platform: "7",
  duration_min: 10,
  transfers: 0,
  products: [line],
  legs: [{ line, category, number: line.replace(/\D/g, ""), from_name: from, to_name: "Bern" }],
});
const WALK_FIRST = conn(5, { line: "21", category: "B", from: "Buchs, Post" });
const walkOnly = { ...conn(6), legs: [] };

const render = (config, connections) => {
  const card = new Card();
  card.setConfig({ entity: "sensor.c", show_clock: false, ...config });
  card.hass = {
    language: "de",
    states: { "sensor.c": { attributes: { connections, from_name: "A", to_name: "B" } } },
  };
  return card.shadowRoot.innerHTML;
};
const rows = (html) => (html.match(/class="cell dep"/g) || []).length;

const list = [conn(-8), conn(3), WALK_FIRST, walkOnly, conn(12, { line: "34", category: "B", from: "Aarau, Bahnhof" })];

// Defaults: every connection with a first leg is listed, no extras.
let html = render({}, list);
assert.equal(rows(html), 5);
assert.ok(!html.includes('class="stale"') && !html.includes('class="grp"'));

// from: keeps only connections boarding at the stop, drops walk-first and walk-only.
html = render({ from: "Aarau" }, list);
assert.equal(rows(html), 3);

// hide_departed: the one that left 8 min ago goes.
assert.equal(rows(render({ hide_departed: true }, list)), 4);

// rows applies to the filtered list, so dropped rows do not eat the limit
// (the sensor's own fetch count still caps what the card can see).
html = render({ from: "Aarau", hide_departed: true, rows: 2 }, list);
assert.equal(rows(html), 2);

// group_by_mode: headings only with more than one mode, trains before buses.
html = render({ group_by_mode: true, from: "Aarau", hide_departed: true }, list);
assert.equal((html.match(/class="grp"/g) || []).length, 2);
assert.ok(html.indexOf(">Zug<") < html.indexOf(">Bus<"));
html = render({ group_by_mode: true, from: "Aarau", hide_departed: true, rows: 1 }, list);
assert.ok(!html.includes('class="grp"'), "one mode needs no heading");

// group_by_mode: a walk-only connection is not listed under any mode.
html = render({ group_by_mode: true }, [conn(3), walkOnly, conn(12, { line: "34", category: "B" })]);
assert.equal(rows(html), 2);

// show_arrival: false drops the arrival and duration columns.
assert.ok(render({}, list).includes(">An<"));
html = render({ show_arrival: false }, list);
assert.ok(!html.includes(">An<") && !html.includes('class="cell arr"') && !html.includes('class="cell dur"'));

// stale_threshold: off by default, on when the first connection left too long ago.
assert.ok(!render({}, list).includes('class="stale"'));
assert.ok(render({ stale_threshold: 300 }, list).includes('class="stale"'));
assert.ok(!render({ stale_threshold: 900 }, list).includes('class="stale"'));

// from: case-insensitive, surrounding spaces ignored.
assert.equal(rows(render({ from: " aarau " }, list)), 3);

// A connection without a timestamp is neither "departed" nor proof of stale data.
const noTs = { ...conn(3), departure_ts: undefined };
assert.equal(rows(render({ hide_departed: true }, [noTs])), 1);
assert.ok(!render({ stale_threshold: 60 }, [noTs]).includes('class="stale"'));

// Timetable mode: the fetched list needs `legs` for from and group_by_mode to work.
const api = (cat, num, station, min) => ({
  from: { departure: "2026-11-12T10:00:00+0100", departureTimestamp: Math.floor((NOW + min * 60000) / 1000), platform: "1", delay: 0 },
  to: { arrival: "2026-11-12T10:10:00+0100", arrivalTimestamp: Math.floor((NOW + (min + 10) * 60000) / 1000), platform: "7" },
  duration: "00d00:10:00",
  transfers: 0,
  products: [`${cat}${num}`],
  sections: [{ journey: { category: cat, number: num }, departure: { station: { name: station }, platform: "1" }, arrival: { station: { name: "Bern" }, platform: "7" } }],
});
globalThis.fetch = async () => ({
  json: async () => ({ connections: [api("S", "9", "Aarau", -30), api("S", "9", "Aarau", 3), api("B", "21", "Buchs, Post", 5)] }),
});
{
  const card = new Card();
  card.setConfig({
    entity: "sensor.c", show_clock: false, from: "Aarau",
    datetime_entity: "datetime.t", mode_entity: "select.m",
  });
  card.hass = {
    language: "de",
    states: {
      "sensor.c": { attributes: { connections: [], from_id: "1", to_id: "2", from_name: "A", to_name: "B" } },
      "datetime.t": { state: new Date(NOW).toISOString().slice(0, 19).replace("T", " ") },
      "select.m": { state: "depart" },
    },
  };
  await new Promise((r) => setTimeout(r, 0));
  card._render();
  assert.equal(rows(card.shadowRoot.innerHTML), 2, "timetable rows keep legs, so `from` works");
  card.setConfig({ ...card._config, hide_departed: true });
  card._render();
  assert.equal(rows(card.shadowRoot.innerHTML), 2, "hide_departed does not apply to a timetable");
}

console.log("connection-card options: ok");
