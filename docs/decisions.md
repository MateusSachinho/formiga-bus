# Decisões técnicas

## 2026-08-18 — Timestamps da API rotulados como UTC ('Z') mas são hora de Brasília

Ao rodar o backend (Fase 1) contra a API real, `vehicles` ficava sempre 0 no
`/health`. Causa: `datetime`/`datetime_envio`/`datetime_servidor` trazem
sufixo `Z` (UTC), mas o valor já é America/Sao_Paulo (UTC-3). Confirmado
comparando os três campos, em vários registros, contra o relógio UTC real —
os três batem ~3h atrás de forma consistente. Interpretar literalmente como
UTC fazia todo ônibus nascer "3h no passado" e o `drop_stale` (180s) zerava
a frota a cada ciclo.

**Decisão:** `transform._parse_ts` troca `Z` por `-03:00` (não `+00:00`) ao
converter para epoch. Brasil aboliu horário de verão em 2019, então UTC-3
fixo é seguro — não precisa de `zoneinfo`/tabela de fusos para isso.
Detalhes e evidência em `docs/api-notes.md`, seção 2.1.

## 2026-08-17 — Schema real da API diverge do ROTEIRO.md

O ROTEIRO.md foi escrito lendo o código de referência, sem acesso de rede.
A Fase 0 (`scripts/probe_api.py` contra a API real) mostrou que o schema
mudou desde a referência. Detalhes completos em `docs/api-notes.md`; resumo:

- `ordem` → `id_veiculo`; `linha` → `servico`; `datahora` (Unix ms) →
  `datetime` (ISO 8601 UTC). `latitude`/`longitude` já são float, não string
  com vírgula.
- **`&linha=` não filtra no servidor** — filtro sempre no backend/cliente.
- **Sem CORS** — proxy backend confirmado como obrigatório.
- **Não existe janela pequena que capture a "frota inteira" de uma vez**: a
  contagem de veículos distintos ainda cresce em janelas de até 10 min, e o
  payload cresce ~2,4 MB/min quase linearmente.

**Decisão:** em vez de aumentar a janela de consulta para tentar pegar a
frota inteira numa chamada só, o `store.py` da Fase 1 vai usar uma janela
curta (90s) a cada poll de 20s e **mesclar por `id_veiculo` no snapshot em
memória entre ciclos**, em vez de substituir o snapshot inteiro a cada
chamada. `drop_stale` continua sendo o mecanismo que remove veículo sumido,
usando a idade do `datetime` (fix do GPS), não do `datetime_servidor`.
Isso muda a redação original da Fase 1 do ROTEIRO ("guarda o snapshot
processado em memória" era ambíguo sobre merge vs. substituição) e precisa
ser seguido literalmente assim na implementação do backend.

**Por quê:** perseguir uma janela grande o bastante para capturar a frota
inteira de uma vez custaria dezenas de MB por chamada a cada 20s — inviável
tanto para a API pública (risco de rate limit/derrubar a fonte) quanto para
o servidor do backend. Mesclar estado entre polls resolve o mesmo problema
sem essa janela grande, e é uma consequência direta do achado de que
`dataInicial`/`dataFinal` não filtram pelo campo `datetime` do jeito que se
esperava (ver `docs/api-notes.md`, seção 2).
