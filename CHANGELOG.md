# Changelog

## 1.4.0 — 2026-08-29

Hardening of the optional real-time token, and a small entity-id change for new entries.

- **The real-time token is checked when you enter it.** The setup and Configure dialogs send one probe request to opentransportdata.swiss before the token is stored. A rejected token (HTTP 401/403) now shows up right in the form instead of being accepted and failing silently; if the service cannot be reached, the form says so and you can try again.
- **A rejected token is logged, once.** Enrichment stays best-effort — a failing OJP request never breaks the board — but the first HTTP 401/403 is now logged at WARNING level with the status code instead of vanishing into debug output. The warning is not repeated until the token has been accepted again in between.
- **New entities get a short tag in their entity id.** The object id suggested for a new station board or connection sensor now ends in the last four characters of its config entry, lower-cased — e.g. `sensor.swiss_transport_zurich_hb_k7q2` — so two stops whose names slugify to the same text no longer end up as `..._2`. Unique ids are unchanged, and **entities you already have keep their ids**; the tag only applies to entities created from now on. The README describes the new shape.
- Fixed: saving a connection entry's Configure dialog dropped the copy of the real-time token that the integration keeps in every entry's options, breaking the single-source-of-truth rule the token sync relies on.
- Fixed: if serving the bundled card file failed once during startup, the integration remembered that as done and the card stayed unavailable until the next restart. The next entry setup now retries.
- SECURITY.md brought up to date: it now describes the optional opentransportdata.swiss token and the one-time Nominatim address lookup instead of claiming the integration uses no credentials.

**Upgrading:** nothing to do. Existing entities keep their ids; an already configured token keeps working and is only re-checked when you save a dialog that contains it.

## 1.3.1 — 2026-08-29

- **New: strategy options.** Keys under `strategy:` are now honoured — `title`, `max_columns`. Unknown keys are ignored, so a typo cannot break the dashboard.
- **New: view strategy.** Next to the dashboard strategy the card file now also registers `ll-strategy-view-...`, so a single view of your own dashboard can be filled by the strategy (`views: - strategy: {type: custom:...}`) while every other view stays hand-editable. Until now the only way to change anything was *Take control*, which permanently stops the dashboard from following your config entries.
- No changes to the integration itself; only the bundled card file and the README.

## 1.3.0 — 2026-08-29

The integration no longer creates or maintains a dashboard. A dashboard strategy replaces it.

- **Removed: the automatic dashboard.** Earlier versions created an "ÖV Abfahrten" / "Departures" dashboard on first setup, added a card for every station or connection, and removed those cards again when an entry was deleted. All of that wrote into Lovelace's storage — another component's configuration, which is not an integration's to manage. The code that did it is gone.
- **Removed: automatic Lovelace resource registration.** The card file is still served by the integration at `/swiss_transport_files/swiss-transport-card.js`, but registering it as a dashboard resource is now a one-time manual step, documented in the README.
- **New: dashboard strategy `custom:swiss-transport`.** It builds the same layout — the Live/Departure/Arrival selector bar on top, then one section per station board and saved connection — but in the browser at display time, writing nothing to your configuration. A station added later appears by itself, so the effect of the old auto-maintained dashboard is preserved without the storage writes. Set it up with an empty dashboard and `strategy: {type: custom:swiss-transport}`; see the README.
- **Minimum Home Assistant version is now 2024.12.0** (was 2024.1.0). The integration already relied on APIs newer than the declared floor; this states the real requirement.
- Added `translations/en.json` so the config and options flow are translated from the packaged translations like every other language.

**Upgrading:** dashboards you already have are left exactly as they are — this release removes the code that would touch them, not the dashboards themselves. If you want the strategy instead, create a new dashboard for it and delete the old one yourself. The Lovelace resource that earlier versions registered for you keeps working; nothing needs to change there. One leftover remains in `.storage/swiss_transport.dashboard` — a small marker file the old code used to remember that it had already created the dashboard. It is never read again and can be deleted when Home Assistant is stopped, or simply left alone.

## 1.2.1 — 2026-07-24

Fixes "too many requests" (HTTP 429) from transport.opendata.ch.

- **Connection polling slowed to 5 minutes** (station boards keep their 90 s cadence). The API allows only 1000 connection queries per day — the previous 90 s poll used 960 of those for a single saved route, so a second route exhausted the quota by midday.
- **Automatic backoff on HTTP 429** — when the daily quota is exhausted, the affected entry pauses for 30 minutes instead of hammering the API, and resumes its normal cadence with the next successful update.

## 1.2.0 — 2026-07-20

Timetable browsing (any date/time, departures or arrivals) and connection details.

- **Timetable browsing** — two new global helper entities, `datetime.swiss_transport_time` and `select.swiss_transport_mode` (`live` / `depart` / `arrive`), let every card show the board for **any date and time** instead of only the live view. A new **`swiss-transport-controls-card`** (Live / Departure / Arrival toggle + date/time picker) is added to the top of the auto-created dashboard and switches all its cards at once; manually placed cards follow via the new `datetime_entity`/`mode_entity` card options. Timetable data is fetched by the browser directly from transport.opendata.ch; in timetable mode the planned schedule is shown (no real-time enrichment) with a "Timetable: …" banner.
- **Arrivals board** — in arrival mode station boards flip to an arrivals view: label "Ankünfte"/"Arrivals" and the direction column switches from *Nach/To* to *Von/From*, showing where each service comes from. Connection cards interpret the selected time as the latest arrival.
- **Connection card: platforms & transfers** — platform columns for both departure and arrival (hidden when empty, as on the station board), plus a transfer line per connection: the change station with its arrival → onward platform.
- **New sensor attributes**: connection entries gain `changes` (transfer stations with platforms); the connection sensor exposes the from/to station ids.

## 1.1.0 — 2026-07-19

Optional real-time enrichment.

- **Real-time via opentransportdata.swiss (OJP 2.0)** — configure a free API token to enrich station boards with fresher, second-accurate delays, **cancellations**, platform changes, **disruption messages** and **occupancy**. Entirely optional: without a token everything keeps working from transport.opendata.ch. The token is entered once (in the station's setup or Configure dialog) and enriches every board.
- **Card additions** (station board): cancelled departures are struck through and marked, a disruption banner is shown above the board, and an occupancy column appears when data is available. New visual-editor toggles `show_occupancy` and `show_alerts`, plus `max_alerts` to control how many disruption messages are shown before "+N more" (0 = all).
- **New sensor attributes**: `realtime` (bool) and `alerts` (disruption messages); `departures` entries gain `cancelled` and `occupancy` when real-time is enabled.
- **Attribution**: the station sensor now credits every source actually used — transport.opendata.ch (search.ch), OpenStreetMap contributors (address), and opentransportdata.swiss (OJP, when real-time is active). See NOTICE.md.

## 1.0.0 — 2026-07-19

Initial release.

- **Departure boards** — the live Abfahrtstafel of any Swiss public transport station (train, tram, bus, ship, cableway). Search by name when adding the integration, repeatable for more stations. One sensor per station: state = next departure (timestamp), attributes = the full upcoming board plus the reverse-geocoded station address.
- **Connections (from → to)** — a saved route, e.g. a daily commute. One sensor per route with the next connections as attributes (departure/arrival times and platforms, delay, duration, transfers, lines used).
- **Two bundled Lovelace cards**, self-registering with a visual editor:
  - `swiss-transport-card` — a real departure board (symbol · time · countdown · destination · platform · info) with a live date/time bar, Swiss-scheme line badges (S-Bahn white, IC/IR red, tram/bus/ship/cableway in mode colors) and transport-mode icons. The platform column is dropped for bus/tram stops.
  - `swiss-transport-connection-card` — a board for a saved route (departure · countdown · line(s) · arrival · duration/transfers).
  - Both show the current date/time and a type label; both can be toggled off in the editor.
- **Automatic dashboard** — an "ÖV Abfahrten" / "Departures" dashboard is created on first setup, with one card per station/connection added and removed automatically.
- Optional filter by transport type and adjustable number of results, live-editable via the options dialog.
- Localized in German, English, French, and Italian.
- Data from the free public transport.opendata.ch timetable API (search.ch); no account required. Provided as-is, without warranty — see the README disclaimer.
