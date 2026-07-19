# Data Sources & Attribution

This integration retrieves data at runtime from the following third-party
services. It is unofficial and not affiliated with, endorsed by, or supported
by any of them or by any transport operator.

## 1. Timetable & departures — transport.opendata.ch (search.ch)

The station boards and connections come from the **transport.opendata.ch** API,
a free service operated by [Opendata.ch](https://opendata.ch/) that is backed by
the timetable of **search.ch**. The API requires no account or key. Please keep
usage reasonable — it is a community service with rate limits.

**Attribution:** *Data: transport.opendata.ch (search.ch)*

## 2. Real-time data (optional) — opentransportdata.swiss (OJP 2.0)

When you configure an API token, station boards are additionally enriched with
real-time information (fresher delays, cancellations, platform changes,
disruption messages and occupancy) from the **Open Journey Planner (OJP 2.0)**
API of [opentransportdata.swiss](https://opentransportdata.swiss/), the official
Swiss open-transport-data platform operated by the *Systemaufgabe
Kundeninformation (SKI)*. A free token is required and obtained by the user.
The data is published as Open Government Data; reuse is permitted with source
attribution. This feature is entirely optional — without a token the
integration works purely from transport.opendata.ch.

**Attribution:** *Real-time: opentransportdata.swiss (OJP)*

## 3. Station address — OpenStreetMap / Nominatim

To show a human-readable address under a station name, the integration performs
a one-time reverse-geocoding lookup per station via **OpenStreetMap Nominatim**.
OpenStreetMap data is © OpenStreetMap contributors, licensed under the
[Open Database License (ODbL)](https://www.openstreetmap.org/copyright).

**Attribution:** *Address: © OpenStreetMap contributors*

---

Every entity this integration creates sets Home Assistant's `attribution`
attribute to credit the sources actually used (surfaced in the entity's "More
Info" dialog). If you build dashboards or republish this data, please keep that
attribution visible.
