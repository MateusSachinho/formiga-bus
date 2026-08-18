import asyncio
import time
from datetime import datetime, timezone

import httpx

from . import config
from .sppo_client import fetch_positions
from .transform import Bus, drop_stale, parse_records, to_geojson


class BusStore:
    """Snapshot em memória, mesclado por id_veiculo entre polls (ver docs/decisions.md:
    a API não filtra por janela do jeito esperado, então uma janela curta + merge entre
    ciclos converge para a frota quase inteira sem baixar dezenas de MB por poll)."""

    def __init__(self):
        self._by_id: dict[str, Bus] = {}
        self.fetched_at: datetime | None = None
        self.source_ok = False

    def _snapshot(self) -> list[Bus]:
        return list(self._by_id.values())

    def _age_s(self) -> float | None:
        if self.fetched_at is None:
            return None
        return (datetime.now(timezone.utc) - self.fetched_at).total_seconds()

    def _envelope(self) -> dict:
        age = self._age_s()
        return {
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "age_s": round(age, 1) if age is not None else None,
            "stale": age is None or age > config.STALE_ENVELOPE_S,
        }

    def get_buses_geojson(self, linha_prefix: str | None) -> dict:
        buses = self._snapshot()
        if linha_prefix:
            prefix = linha_prefix.upper()
            buses = [b for b in buses if b.linha.upper().startswith(prefix)]
        geo = to_geojson(buses)
        geo.update(self._envelope())
        return geo

    def health(self) -> dict:
        age = self._age_s()
        return {
            "status": "ok" if self.source_ok else "degraded",
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "age_s": round(age, 1) if age is not None else None,
            "vehicles": len(self._by_id),
            "source_ok": self.source_ok,
        }

    async def poll_forever(self, client: httpx.AsyncClient) -> None:
        backoff = config.POLL_INTERVAL_S
        while True:
            try:
                raw = await fetch_positions(client, config.FETCH_WINDOW_S)
                now = int(time.time())
                for b in parse_records(raw):
                    cur = self._by_id.get(b.id)
                    if cur is None or b.ts > cur.ts:
                        self._by_id[b.id] = b
                fresh = drop_stale(self._snapshot(), config.STALE_AFTER_S, now)
                self._by_id = {b.id: b for b in fresh}
                self.fetched_at = datetime.now(timezone.utc)
                self.source_ok = True
                backoff = config.POLL_INTERVAL_S
            except Exception:
                self.source_ok = False
                backoff = min(backoff * 2, config.POLL_MAX_BACKOFF_S)
            await asyncio.sleep(backoff)
