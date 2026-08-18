"""Sonda a API dados.mobilidade.rio/gps/sppo. Fase 0 do ROTEIRO.

Uso:
    python scripts/probe_api.py [--minutes N] [--linha 554] [--out docs/api-sample.json]
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

BASE_URL = "https://dados.mobilidade.rio/gps/sppo"


def build_url(minutes: int, linha: str | None = None, end: datetime | None = None) -> str:
    end = end or datetime.now()
    start = end - timedelta(minutes=minutes)
    params = {
        "dataInicial": start.strftime("%Y-%m-%d %H:%M:%S"),
        "dataFinal": end.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if linha:
        params["linha"] = linha
    return f"{BASE_URL}?{urllib.parse.urlencode(params)}"


def fetch(url: str) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "formiga-bus-probe/0.1"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
            elapsed = time.monotonic() - t0
            return resp.status, body, dict(resp.headers), elapsed
    except urllib.error.HTTPError as e:
        body = e.read()
        elapsed = time.monotonic() - t0
        return e.code, body, dict(e.headers or {}), elapsed


def summarize(label: str, url: str, status: int, body: bytes, headers: dict, elapsed: float) -> dict:
    print(f"\n=== {label} ===")
    print(f"URL: {url}")
    print(f"status: {status}  tempo: {elapsed:.2f}s  bytes: {len(body)}")
    cors = headers.get("Access-Control-Allow-Origin")
    print(f"CORS (Access-Control-Allow-Origin): {cors!r}")

    result = {
        "label": label,
        "url": url,
        "status": status,
        "elapsed_s": round(elapsed, 3),
        "size_bytes": len(body),
        "cors_header": cors,
    }

    if status != 200:
        print(f"AVISO: status != 200. Corpo (primeiros 500 bytes): {body[:500]!r}")
        result["error"] = f"status {status}"
        return result

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        print(f"AVISO: corpo não é JSON válido: {e}")
        result["error"] = f"json decode error: {e}"
        return result

    if not isinstance(data, list):
        print(f"AVISO: raiz do JSON não é uma lista, é {type(data).__name__}")
        result["error"] = "root is not a list"
        result["root_type"] = type(data).__name__
        return result

    n = len(data)
    keys = sorted(data[0].keys()) if n else []
    # ponytail: nomes de campo variam entre versões da API (viu-se 'ordem'/'linha'/'datahora'
    # na referência e 'id_veiculo'/'servico'/'datetime' na prática); tenta os dois.
    id_key = "ordem" if keys and "ordem" in keys else "id_veiculo"
    linha_key = "linha" if keys and "linha" in keys else "servico"
    ts_key = "datahora" if keys and "datahora" in keys else "datetime"

    ids = {r.get(id_key) for r in data if isinstance(r, dict)}
    timestamps = [r.get(ts_key) for r in data if isinstance(r, dict) and r.get(ts_key)]
    zero_or_null_coords = sum(
        1
        for r in data
        if isinstance(r, dict)
        and (
            r.get("latitude") in (None, 0, "0", "0,0", "0.0")
            or r.get("longitude") in (None, 0, "0", "0,0", "0.0")
        )
    )

    print(f"registros: {n}")
    print(f"'{id_key}' distintos (veículos): {len(ids)}")
    print(f"chaves do primeiro objeto: {keys}")
    if timestamps:
        print(f"range '{ts_key}': {min(timestamps)} .. {max(timestamps)}")
    print(f"registros com lat/lon 0 ou nulos: {zero_or_null_coords}")

    result.update(
        {
            "n_records": n,
            "id_key_used": id_key,
            "n_distinct_vehicles": len(ids),
            "keys_first_object": keys,
            "timestamp_key_used": ts_key,
            "timestamp_min": min(timestamps) if timestamps else None,
            "timestamp_max": max(timestamps) if timestamps else None,
            "zero_or_null_coord_records": zero_or_null_coords,
        }
    )
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=2, help="janela principal em minutos")
    ap.add_argument("--linha", default=None, help="testar filtro por linha, ex: 554")
    ap.add_argument("--out", default="docs/api-sample.json", help="onde salvar a resposta crua da janela principal")
    args = ap.parse_args()

    summaries = []

    # 1) janela principal -> salva amostra crua
    url = build_url(args.minutes)
    status, body, headers, elapsed = fetch(url)
    summaries.append(summarize(f"janela principal ({args.minutes} min)", url, status, body, headers, elapsed))
    if status == 200:
        with open(args.out, "wb") as f:
            f.write(body)
        print(f"\nSalvo em {args.out}")
    else:
        print(f"\nNÃO salvo em {args.out} (status {status})")

    # 2) filtro por linha, se pedido
    if args.linha:
        url_l = build_url(args.minutes, linha=args.linha)
        s, b, h, e = fetch(url_l)
        summaries.append(summarize(f"filtro linha={args.linha}", url_l, s, b, h, e))
        try:
            data_filtered = json.loads(b) if s == 200 else []
            if isinstance(data_filtered, list) and data_filtered:
                linha_key = "linha" if "linha" in data_filtered[0] else "servico"
                linhas_no_filtrado = {r.get(linha_key) for r in data_filtered if isinstance(r, dict)}
                print(f"valores de '{linha_key}' na resposta filtrada: {linhas_no_filtrado}")
                print(
                    "-> parâmetro 'linha' parece "
                    + ("RESPEITADO" if linhas_no_filtrado <= {args.linha} else "IGNORADO (servidor não filtrou)")
                )
        except Exception as e:
            print(f"não foi possível comparar filtro: {e}")

    # 3) janelas de tamanhos diferentes: tempo de resposta e contagem de veículos
    for m in (1, 5, 10):
        url_m = build_url(m)
        s, b, h, e = fetch(url_m)
        summaries.append(summarize(f"janela {m} min", url_m, s, b, h, e))

    print("\n\n=== RESUMO JSON (cole em docs/api-notes.md) ===")
    print(json.dumps(summaries, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
