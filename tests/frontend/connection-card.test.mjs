// Self-check for the connection card's board options — run:
//   node tests/frontend/connection-card.test.mjs
//
// The card renders in a browser, so this shims the few DOM pieces it touches
// and asserts on the generated markup. Covers `from`, `hide_departed`,
// `group_by_mode`, `show_arrival` and `stale_threshold`, and that a card
// without any of them renders as before.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

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
// The card loads its line colours from the integration's static path; serve the
// real file from disk, everything else is "no network".
const LINE_COLORS = new URL("../../custom_components/swiss_transport/frontend/line-colors.json", import.meta.url);
globalThis.fetch = async (url) => {
  if (String(url).endsWith("line-colors.json")) {
    return { ok: true, json: async () => JSON.parse(readFileSync(LINE_COLORS, "utf8")) };
  }
  throw new Error("no network in tests");
};
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
const conn = (min, { line = "S9", category = "S", from = "Aarau", delay = 0, operator } = {}) => ({
  departure: new Date(NOW + min * 60000).toISOString().replace("Z", "+0000"),
  departure_ts: Math.floor((NOW + min * 60000) / 1000),
  delay,
  dep_platform: "1",
  arrival: new Date(NOW + (min + 10) * 60000).toISOString().replace("Z", "+0000"),
  arr_platform: "7",
  duration_min: 10,
  transfers: 0,
  products: [line],
  legs: [{ line, category, number: line.replace(/\D/g, ""), operator, from_name: from, to_name: "Bern" }],
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

// Let the card fetch its line colours once, so later renders have them.
await (async () => {
  const card = new Card();
  card.setConfig({ entity: "sensor.c" });
  card.hass = { language: "de", states: { "sensor.c": { attributes: { connections: [] } } } };
  await new Promise((r) => setTimeout(r, 0));
})();

let html;

// Line colours: RBS and BLS trains get their line colour from the table, other
// operators keep the plain train badge.
html = render({}, [conn(3, { operator: "RBS" })]);
assert.ok(html.includes("background:#fa2d18"), "RBS S9 is red");
html = render({}, [conn(3, { line: "S3", operator: "BLS-bls" })]); // the API calls BLS "BLS-bls"
assert.ok(html.includes("background:#8868b3"), "BLS S3 is purple");
html = render({}, [conn(3, { line: "S52", operator: "BLS-bls" })]);
assert.ok(html.includes("background:#f7cf39;color:#000000"), "white label on yellow turns black");
// The product text can carry a space ("S 9"); a bus "9" ahead of the train does not claim it.
{
  const c = conn(3, { operator: "RBS" });
  c.products = ["S 9"];
  c.legs.unshift({ line: "9", category: "B", number: "9", operator: "BLT", from_name: "Aarau", to_name: "x" });
  assert.ok(render({}, [c]).includes("background:#fa2d18"), "train badge keeps the RBS colour");
}
// Existing bus/tram tables keep their text colour (VBZ 6 is light with white text).
html = render({}, [conn(3, { line: "6", category: "T", operator: "VBZ" })]);
assert.ok(!html.includes("color:#000000"), "existing tables are not flipped");
// line_label number: a bus "9" after the train never takes the train colour.
{
  const c = conn(3, { operator: "RBS" });
  c.products = ["9"];
  c.legs[0].line = "9";
  c.legs.push({ line: "9", category: "B", number: "9", operator: "BLT", from_name: "x", to_name: "y" });
  assert.ok(!render({}, [c]).includes("background:#fa2d18"), "numeric label matches no train by itself");
}
html = render({}, [conn(3, { operator: "SBB" })]);
assert.ok(!html.includes("background:#fa2d18"), "an operator without a table keeps the plain badge");
html = render({ style: "classic" }, [conn(3, { operator: "RBS" })]);
assert.ok(!html.includes("background:#fa2d18"), "classic style stays uncoloured");

// Station board: same colours for trains.
{
  const Board = defined["swiss-transport-card"];
  const card = new Board();
  card.setConfig({ entity: "sensor.b", show_clock: false });
  const dep = (op) => ({
    line: "S9", category: "S", number: "9", operator: op, to: "Bern",
    departure: new Date(NOW + 180000).toISOString().replace("Z", "+0000"),
    departure_ts: Math.floor((NOW + 180000) / 1000), delay: 0, platform: "1",
  });
  card.hass = { language: "de", states: { "sensor.b": { attributes: { station_name: "Aarau", departures: [dep("RBS")], departure_count: 1 } } } };
  assert.ok(card.shadowRoot.innerHTML.includes("background:#fa2d18"), "board: RBS S9 is red");
  // line_label "category" leaves only "S" as the label; the colour still follows category + number.
  const only = { ...dep("RBS"), line: "S" };
  card.hass = { language: "de", states: { "sensor.b": { attributes: { station_name: "Aarau", departures: [only], departure_count: 1 } } } };
  assert.ok(card.shadowRoot.innerHTML.includes("background:#fa2d18"), "board: label S still finds S9");
}

// Defaults: every connection with a first leg is listed, no extras.
html = render({}, list);
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

// Timetable mode names the lines as the sensor does (attribute line_label):
// bus and tram by number, trains by the chosen label.
for (const [labelMode, train] of [[undefined, "S"], ["category", "S"], ["full", "S9"], ["number", "9"]]) {
  const card = new Card();
  card.setConfig({ entity: "sensor.c", show_clock: false, datetime_entity: "datetime.t", mode_entity: "select.m" });
  card.hass = {
    language: "de",
    states: {
      "sensor.c": { attributes: { connections: [], from_id: "1", to_id: "2", from_name: "A", to_name: "B", line_label: labelMode } },
      "datetime.t": { state: new Date(NOW).toISOString().slice(0, 19).replace("T", " ") },
      "select.m": { state: "depart" },
    },
  };
  await new Promise((r) => setTimeout(r, 0));
  const lines = card._fetched.map((con) => con.legs[0].line);
  assert.deepEqual(lines, [train, train, "21"], `timetable legs with line_label ${labelMode}`);
}

console.log("connection-card options: ok");
