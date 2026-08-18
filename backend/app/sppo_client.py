from datetime import datetime, timedelta

import httpx

BASE_URL = "https://dados.mobilidade.rio/gps/sppo"


async def fetch_positions(client: httpx.AsyncClient, window_s: int) -> list[dict]:
    """GET na janela [agora - window_s, agora]. Levanta em erro de rede/HTTP;
    quem chama decide o que fazer (retry, backoff, manter snapshot antigo)."""
    end = datetime.now()
    start = end - timedelta(seconds=window_s)
    params = {
        "dataInicial": start.strftime("%Y-%m-%d %H:%M:%S"),
        "dataFinal": end.strftime("%Y-%m-%d %H:%M:%S"),
    }
    resp = await client.get(BASE_URL, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()
