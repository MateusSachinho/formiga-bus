# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`formiga-bus`: mobile-first web app showing Rio de Janeiro's buses moving live on a dark map, with a per-line filter and a tap-for-detail panel. Metaphor: fleet seen from above as an anthill — small dense dots, not icons.

Two independently deployed pieces:
- `backend/` — FastAPI proxy/poller in front of the city's public GPS API (`dados.mobilidade.rio/gps/sppo`), deployed to Render.
- `app/` — vanilla TypeScript + Vite + MapLibre GL JS frontend, deployed to Vercel.

## Commands

### Backend (`backend/`)

```bash
# setup (venv already exists at backend/.venv; recreate with: python -m venv .venv)
.venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt

# run dev server (reads env vars via backend/app/config.py, see .env.example at repo root)
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000

# tests
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m pytest tests/test_transform.py::test_drop_stale_remove_quem_nao_transmite -q
```

### Frontend (`app/`)

```bash
npm install
npm run dev        # Vite dev server; auto-picks a free port starting at 5173
npm run build       # tsc (type-check, noEmit) + vite build — this is also the type-check command
npm run preview     # serve the production build locally
```

Frontend has no automated tests (ROTEIRO.md planned Vitest; never added — `npm run build`'s `tsc` step is the only current safety net).

### Deploy (manual, no CI on either side — `git push` alone does not redeploy)

```bash
# backend → Render, from repo root; render.yaml is the Blueprint (Docker runtime)
# redeploy via Render dashboard or CLI after pushing to GitHub

# frontend → Vercel, from app/ (already linked, see app/.vercel/project.json)
npx vercel --prod
```

## Architecture

### Backend: poll-merge-serve, never call upstream from a request

`backend/app/`:
- `sppo_client.py` — one `GET` against the city API for a `[now - window_s, now]` window. No retry logic here; the caller decides.
- `transform.py` — **pure functions, no I/O**, fully testable without network: `parse_records` (validate + bounding-box filter for Rio), `drop_stale`, `to_geojson`.
- `store.py` — `BusStore` holds the fleet as an in-memory `dict[id_veiculo, Bus]`. A background task (`poll_forever`, started from `main.py`'s `lifespan`) fetches every `POLL_INTERVAL_S` (default 20s) and **merges by `id_veiculo` across cycles** — it does not replace the whole snapshot on each call.
- `routes.py` — HTTP handlers only ever read `store`'s in-memory snapshot. They never call the upstream API directly, so `/api/v1/buses` always responds instantly regardless of upstream latency.

This merge-across-polls design exists because the upstream API has no window small enough to capture the whole fleet in one call (payload grows ~2.4MB/min with no plateau up to 10 min) — see `docs/api-notes.md` and `docs/decisions.md` for the full investigation. Do not "fix" this by requesting a bigger window.

**Timezone landmine:** the upstream API labels `datetime`/`datetime_envio`/`datetime_servidor` with `Z` (UTC) but the value is actually America/Sao_Paulo local time. `transform._parse_ts` replaces `Z` with `-03:00` (not `+00:00`) — this is deliberate, not a bug. Brazil has had no DST since 2019, so the fixed offset is safe.

On upstream failure, `poll_forever` keeps the last good snapshot and backs off exponentially (`POLL_INTERVAL_S` → doubling → `POLL_MAX_BACKOFF_S`), resetting to normal on the next success. `/api/v1/buses` and `/api/v1/health` responses always carry `stale`/`age_s` so the frontend can show a "last known position" state instead of going blank.

### Frontend: three files, no framework

`app/src/`:
- `api.ts` — `fetchBuses()`, typed response shapes.
- `map.ts` — owns the MapLibre instance: the basemap is a **vector style URL** (OpenFreeMap `liberty`, OSM data, no API key), plus `addBusLayer()` for the buses `circle` layer — never `Marker`, thousands of DOM nodes would freeze the phone — `setBuses()`, `fitToBuses()`.
- `main.ts` — orchestrates polling (20s interval, paused on `visibilitychange`), the line filter (debounced, `localStorage`-persisted), and the bus-detail panel (click on a circle → `queryRenderedFeatures`).

No framework: the UI is one screen (map + search + status bar + bottom sheet) with no shared state complex enough to justify React/Zustand — see `docs/decisions.md`.

**MapLibre worker gotcha — now fatal for the whole map.** The basemap is vector, so it is rendered *through* the worker; a broken worker no longer costs you just the bus dots (how the two bundler bugs below first showed up), it blanks the entire map. Test every change against the production build, not only the dev server. `maplibre-gl`'s auto worker detection breaks both in Vite dev (esbuild's pre-bundler rewrites how the worker is instantiated, request hangs forever) and in production build (the worker's own `import` of a sibling `maplibre-gl-shared.mjs` isn't followed through a `?url` import, and a 404 there resolves as a silent 200 SPA-fallback HTML, not a JS error). Fix in place: `maplibre-gl-worker.mjs` + `maplibre-gl-shared.mjs` are copied verbatim into `app/public/maplibre/`, and `map.ts` points at them directly via `setWorkerUrl(...)`. **If you bump the `maplibre-gl` version, recopy both files from `node_modules/maplibre-gl/dist/`.**

**Style URL means the bus layer is added after `load`.** With `style` as a URL
you cannot declare the `buses` source/layer in the `Map` constructor — the style
does not exist yet. `addBusLayer(map)` is called from `main.ts`'s `map.on("load")`.
Layer-scoped handlers (`map.on("click", "buses", ...)`) may still be registered at
module top level: MapLibre resolves the layer at event time.

The old CARTO raster basemap and its `raster-brightness-min` slider are gone —
see `docs/decisions.md` (2026-09-25) for why, including why `tile.openstreetmap.org`
was rejected (no retina tiles + the OSMF policy forbids distributing an app with them,
which the ROTEIRO's Fase 6 APK would do).

Attribution sits **top-right**: at MapLibre's default (bottom-right) the search bar
covers the control, and OpenFreeMap requires visible attribution.

### Data flow

`dados.mobilidade.rio/gps/sppo` → backend poller (merge by `id_veiculo`, drop stale, bounding-box filter) → in-memory GeoJSON snapshot → frontend polls `/api/v1/buses` every 20s → MapLibre `circle` layer.

### `// ponytail:` comments

Comments prefixed `ponytail:` mark a deliberate simplification with a known ceiling (e.g. a global lock, a hardcoded value, code cut for having no real caller). They name the tradeoff and when to revisit it — read them before "fixing" what looks like an oversight.

## Documentation map

- `docs/ROTEIRO.md` — the original phase-by-phase implementation plan. Written *before* Fase 0 (probing the real API), so its assumed API schema and some endpoint/field names (`/lines`, `/bus/{ordem}/track`, `ordem`, `linha`, ms timestamps) are **wrong** — treat it as historical intent, not current fact. `docs/decisions.md` records every place reality diverged from it.
- `docs/api-notes.md` — actual API schema and behavior, found by probing (`scripts/probe_api.py`), including the timezone bug and the "no small window captures the full fleet" finding.
- `docs/decisions.md` — technical decisions and why, in chronological order (most recent first is not guaranteed — read dates).
- Endpoints described in ROTEIRO.md but not present in the code (`/api/v1/lines`, `/api/v1/bus/{ordem}/track`) were built ahead of any real caller and removed in a ponytail-audit pass; reintroduce only when a feature actually needs them.
