import json
from datetime import datetime, timezone
from pathlib import Path

from app.transform import Bus, drop_stale, parse_records, to_geojson

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "sample.json").read_text(encoding="utf-8"))


def test_parse_records_amostra_real():
    buses = parse_records(FIXTURE)
    assert len(buses) == len(FIXTURE)  # nenhum registro real da amostra deveria ser descartado
    assert all(isinstance(b.lat, float) and isinstance(b.ts, int) for b in buses)


def test_parse_records_descarta_lixo():
    lixo = [
        {},  # sem nada
        {"id_veiculo": "X1", "servico": "100", "latitude": 0, "longitude": 0,
         "velocidade": 0, "datetime": "2026-08-17T10:00:00Z"},  # coord zero
        {"id_veiculo": "X2", "servico": "100", "latitude": -20.0, "longitude": -40.0,
         "velocidade": 0, "datetime": "2026-08-17T10:00:00Z"},  # fora do bounding box do Rio
        {"id_veiculo": "X3", "servico": "100", "latitude": "abc", "longitude": -43.2,
         "velocidade": 0, "datetime": "2026-08-17T10:00:00Z"},  # lat inválida
        {"id_veiculo": "X4", "latitude": -22.9, "longitude": -43.2,
         "velocidade": 0, "datetime": "2026-08-17T10:00:00Z"},  # sem servico
    ]
    assert parse_records(lixo) == []


def test_parse_records_mantem_valido_com_velocidade_ausente():
    valido = [{"id_veiculo": "X5", "servico": "SN", "latitude": -22.9, "longitude": -43.2,
               "datetime": "2026-08-17T10:00:00Z"}]
    buses = parse_records(valido)
    assert len(buses) == 1
    assert buses[0].vel == 0.0
    # 'datetime' vem rotulado 'Z' mas é hora de Brasília (UTC-3), não UTC de verdade
    assert buses[0].ts == int(datetime(2026, 8, 17, 13, 0, 0, tzinfo=timezone.utc).timestamp())


def test_drop_stale_remove_quem_nao_transmite():
    fresco = Bus(id="A", linha="100", lat=-22.9, lon=-43.2, vel=0, ts=1000)
    velho = Bus(id="B", linha="100", lat=-22.9, lon=-43.2, vel=0, ts=700)
    result = drop_stale([fresco, velho], max_age_s=180, now=1000)
    assert result == [fresco]


def test_to_geojson_arredonda_coordenadas():
    b = Bus(id="A", linha="554", lat=-22.906812345, lon=-43.172900001, vel=12.3, ts=1000)
    geo = to_geojson([b])
    assert geo["type"] == "FeatureCollection"
    feat = geo["features"][0]
    assert feat["geometry"]["coordinates"] == [-43.1729, -22.90681]
    assert feat["properties"] == {"id": "A", "linha": "554", "vel": 12.3, "ts": 1000}
