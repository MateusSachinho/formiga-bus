# Decisões técnicas

## 2026-08-18 — Vite pré-bundlando maplibre-gl trava o worker pra sempre

Rodando o app de verdade no navegador (não só `tsc --noEmit`): o mapa carregava,
o basemap aparecia, mas nenhum ônibus renderizava — nem um ponto de teste
manual no centro exato do mapa. `map.loaded()`/`source.loaded()` ficavam
`false` para sempre. Causa: `node_modules/.vite/deps/maplibre-gl-worker.mjs`
ficava com request **pending indefinidamente** (confirmado via
`read_network_requests`). O pré-bundler do Vite (esbuild) reescreve o jeito
que o maplibre-gl v6 instancia seu worker (`new Worker(new URL(...), {type:
'module'})`) de um jeito que a requisição do worker nunca resolve — camadas
raster (basemap) não dependem do worker e renderizam normal, mascarando o
problema até alguém realmente olhar pros pontos.

**Decisão:** `app/vite.config.ts` com `optimizeDeps.exclude: ["maplibre-gl"]`.
Resolve porque tira o maplibre-gl do pré-bundle do esbuild, deixando o
`import` original (que o próprio maplibre-gl já empacota corretamente)
intacto. Confirmado ao vivo: os 2700+ pontinhos azuis renderizam depois do
fix. Isso é um problema conhecido de bundlers com o worker do maplibre-gl —
se atualizar a versão do pacote no futuro, testar de novo antes de assumir
que ainda é necessário.

## 2026-08-18 — Frontend sem framework (vanilla TS, não React)

O ROTEIRO original previa React 18. Revisando o escopo real da UI — um mapa,
uma busca, uma barra de status e um bottom sheet — não há árvore de
componentes, rotas ou estado compartilhado complexo o bastante para
justificar um framework. React+ReactDOM é peso de bundle que o app paga em
toda carga inicial, direto contra o requisito "carregar rápido" em 4G.

**Decisão:** TypeScript vanilla + Vite (só como bundler/dev server) +
MapLibre GL JS direto. Capacitor empacota a pasta `dist/` do mesmo jeito,
com ou sem framework por baixo. Zustand cai fora pelo mesmo motivo — vira
um módulo com algumas variáveis e funções.

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
