"""Parse -> dedup -> GeoJSON. Funções puras, sem I/O, testáveis sem rede.

Schema real da API (ver docs/api-notes.md), não o da referência:
id_veiculo (não 'ordem'), servico (não 'linha'), datetime ISO 8601 UTC
(não 'datahora' em Unix ms), latitude/longitude já são float.
"""
from dataclasses import dataclass
from datetime import datetime

RIO_LAT_MIN, RIO_LAT_MAX = -23.1, -22.7
RIO_LON_MIN, RIO_LON_MAX = -43.8, -43.1


@dataclass(frozen=True)
class Bus:
    id: str
    linha: str
    lat: float
    lon: float
    vel: float
    ts: int  # epoch segundos, UTC


def _parse_ts(raw: str) -> int:
    # A API rotula 'datetime'/'datetime_envio'/'datetime_servidor' com 'Z' (UTC), mas o
    # valor já vem em horário de Brasília (America/Sao_Paulo, UTC-3, sem horário de verão
    # desde 2019). Confirmado comparando com o relógio real: ver docs/decisions.md.
    return int(datetime.fromisoformat(raw.replace("Z", "-03:00")).timestamp())


def parse_records(raw: list[dict]) -> list[Bus]:
    buses = []
    for r in raw:
        try:
            id_ = r["id_veiculo"]
            linha = r["servico"]
            if not id_ or not linha:
                continue
            lat, lon = float(r["latitude"]), float(r["longitude"])
            if lat == 0 or lon == 0:
                continue
            if not (RIO_LAT_MIN <= lat <= RIO_LAT_MAX and RIO_LON_MIN <= lon <= RIO_LON_MAX):
                continue
            ts = _parse_ts(r["datetime"])
            vel = float(r.get("velocidade") or 0)
            buses.append(Bus(id=id_, linha=linha, lat=lat, lon=lon, vel=vel, ts=ts))
        except (KeyError, TypeError, ValueError):
            continue
    return buses


def drop_stale(buses: list[Bus], max_age_s: int, now: int) -> list[Bus]:
    return [b for b in buses if now - b.ts <= max_age_s]


def to_geojson(buses: list[Bus]) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(b.lon, 5), round(b.lat, 5)]},
                "properties": {"id": b.id, "linha": b.linha, "vel": b.vel, "ts": b.ts},
            }
            for b in buses
        ],
    }
