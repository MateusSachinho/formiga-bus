import os

POLL_INTERVAL_S = int(os.getenv("POLL_INTERVAL_S", "20"))
# ponytail: janela curta, não a "frota inteira" numa chamada só — ver docs/decisions.md.
# O store mescla por id_veiculo entre polls, então a frota converge em poucos ciclos.
FETCH_WINDOW_S = int(os.getenv("FETCH_WINDOW_S", "90"))
STALE_AFTER_S = int(os.getenv("STALE_AFTER_S", "180"))
STALE_ENVELOPE_S = int(os.getenv("STALE_ENVELOPE_S", "90"))
POLL_MAX_BACKOFF_S = int(os.getenv("POLL_MAX_BACKOFF_S", "120"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]
