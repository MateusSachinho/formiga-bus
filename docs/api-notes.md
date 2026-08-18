# Fase 0 — Achados sobre a API dados.mobilidade.rio/gps/sppo

Sondagem feita com `scripts/probe_api.py` em **2026-08-17, ~20:47 BRT (23:47 UTC)** —
noite, pós-pico. Só há dados de **um** horário até agora (ver "Pendências" no fim).

**ATENÇÃO: o formato real diverge do descrito no ROTEIRO.md** (que foi escrito a
partir da leitura do código de referência, sem acesso à API). Ver seção 1.

---

## 1. Schema real ≠ schema assumido

| Assumido (ROTEIRO / referência) | Real (observado agora) |
|---|---|
| `ordem` (chave de dedup) | não existe → chave de dedup é **`id_veiculo`** (ex.: `"B58062"`) |
| `linha` | não existe → número da linha é **`servico`** (string) |
| `latitude`/`longitude` como **string com vírgula** (`"-22,90342"`) | já vêm como **float** (`-22.88273`). Não precisa `replace(",", ".")`. |
| `datahora`/`datahoraenvio`/`datahoraservidor` em **Unix ms** | strings **ISO 8601 UTC** com `Z`: `datetime`, `datetime_envio`, `datetime_servidor` (ex.: `"2026-08-17T23:42:09Z"`) |
| — | campos novos: `direcao` (rumo em graus, 0–360), `sentido` (`"I"`/`"C"`/`"V"`/`""`), `route_id` (sempre `null` na amostra), `trip_id`, `shape_id` |

**Consequência prática para a Fase 1:** `transform.py` deve ser escrito para o
schema real (`id_veiculo`, `servico`, `datetime` ISO), não para o da
referência. `route_id` pode ser ignorado (100% `null` na amostra).

Ver `docs/decisions.md` para o registro formal desse desvio.

---

## 2. Respostas às perguntas da Fase 0

**Tamanho do payload / registros / `ordem` distintas / chaves / range de tempo**
→ ver `docs/api-sample.json` (janela de 2 min, resposta crua) e a tabela da
seção 3 abaixo para os outros tamanhos de janela.

**O endpoint aceita filtro por linha (`&linha=554`)?**
**Não. O parâmetro é ignorado.** Pedi `&linha=554` numa janela de 2 min e a
resposta trouxe 289 valores distintos de `servico` (todas as linhas ativas,
não só a 554). O filtro por linha **tem que ser feito depois do fetch**,
como o ROTEIRO já previa como plano B — mas aqui não há plano A.

**Tempo de resposta por tamanho de janela**

| Janela | Tempo | Bytes | Registros | Veículos distintos (`id_veiculo`) |
|---|---|---|---|---|
| 1 min | 3.0s | 2.24 MB | 6.688 | 2.940 |
| 2 min | 3.9s | 4.86 MB | 14.529 | 3.061 |
| 5 min | 7.6s | 12.13 MB | 36.238 | 3.215 |
| 10 min | 8.4s | 24.50 MB | 73.182 | 3.370 |

**Qual a menor janela que ainda retorna a frota inteira?**
**Não encontrei um platô — a contagem de veículos distintos ainda está
subindo em 10 min** (+4,1% de 1→2min, +5,0% de 2→5min, +4,8% de 5→10min).
Ou seja, não existe uma janela "mágica" pequena que capture 100% da frota
de uma vez: o payload cresce ~2,4 MB por minuto de janela de forma quase
linear, então perseguir "frota inteira numa única chamada" significa
janelas de dezenas de minutos e dezenas de MB — inviável para poll a cada 20s.

**Achado mais importante da Fase 0, que muda o desenho da Fase 1:**
Dentro de uma janela de 2 min, o campo `datetime` (fix do GPS) variou de
`22:34:56` até `23:47:22` — ou seja, **`dataInicial`/`dataFinal` claramente
não filtram pelo campo `datetime`** (senão não apareceria um fix de mais de
1h atrás numa janela de 2 min). O filtro do servidor parece ser por
recebimento (`datetime_servidor` ou `datetime_envio`), e cada veículo carrega
seu **último fix conhecido**, mesmo que antigo.

Isso muda a estratégia: **não é preciso perseguir uma janela grande.** O
poller do backend (Fase 1) já vai rodar a cada 20s e manter um snapshot **em
memória que acumula por `id_veiculo` entre ciclos** (não substitui do zero a
cada chamada). Com isso, uma janela curta (60–90s, cobrindo folgadamente o
intervalo de poll) chamada a cada 20s converge para a frota quase inteira em
poucos ciclos, e o `drop_stale` (usando a idade do **`datetime`**, não do
`datetime_servidor`) continua sendo o mecanismo certo para remover veículos
que pararam de transmitir. **Recomendação: janela de 90s, poll a cada 20s,
merge por `id_veiculo` no `store.py` em vez de substituição total do
snapshot a cada ciclo.** Isso precisa ficar explícito na Fase 1 (o ROTEIRO
atual não deixa claro se o snapshot é substituído ou mesclado).

**CORS?**
**Não há CORS.** Nenhuma das respostas trouxe `Access-Control-Allow-Origin`.
Confirma que o backend-proxy é obrigatório, não opcional — fetch direto do
navegador vai ser bloqueado.

**`latitude`/`longitude` iguais a 0 ou nulos?**
Nenhum na amostra (14.529 registros, 0 ocorrências). Mas **há outliers fora
do bounding box do Rio**: `latitude` variou até `-20.864` e `longitude` até
`-41.105` — bem fora de `-23.1..-22.7` / `-43.8..-43.1` (mais perto da
região de Campos/Cabo Frio, quase certamente erro de GPS, não veículo real
fora da cidade). **Confirma que o filtro por bounding box do `transform.py`,
já previsto no ROTEIRO, é necessário e não paranoia.**

**Outros achados não perguntados explicitamente, mas relevantes:**
- `servico` traz muitos valores que não são linha nenhuma: `GARAGEM`,
  `MANUTENCAO`, `TREINO`, `FORA DE OP`, `RESERVADO`, `ESPECIAL`, `"1 GAR"`.
  A Fase 1/5 (filtro e `/lines`) devem decidir se escondem esses
  pseudo-serviços da lista de sugestões (eles não são linhas que um usuário
  vai buscar).
- `trip_id` vem vazio (`""`) em 391/14.529 registros — normalmente junto de
  `servico` operacional (garagem etc.), não erro de parsing.
- `route_id` é `null` em 100% da amostra — campo morto, ignorar.

---

## 2.1. Achado feito ao testar o backend (Fase 1): os timestamps mentem sobre o fuso

Descoberto rodando o backend de verdade contra a API: **`datetime`,
`datetime_envio` e `datetime_servidor` vêm com sufixo `Z` (UTC), mas o valor
já está em horário de Brasília (America/Sao_Paulo, UTC-3).** Comparando os
três campos com o relógio UTC real da máquina, os três batem consistentemente
~3h "no passado" se interpretados literalmente como UTC — `datetime_servidor`
(que deveria ser quase igual a "agora", já que é o instante de recebimento)
ficava ~10.814s atrás do UTC real, ou seja, quase exatamente 3h.

**Isso não é side-effect de fuso da máquina que roda o backend** — o parsing
usa `datetime.fromisoformat` que respeita o offset embutido na string, então
o bug é da própria API rotulando errado o campo.

**Consequência:** se não corrigido, todo ônibus nasce "3h no passado" e o
`drop_stale` (janela de 180s) descarta a frota inteira a cada poll —
`vehicles: 0` sempre. `transform.py` corrige isso trocando o `Z` por
`-03:00` em vez de `+00:00` ao converter para epoch. Ver `docs/decisions.md`.

---

## 3. Pendências (não pulei por preguiça — é a regra "não inventar dados")

- **Só testei um horário** (noite, pós-pico, 2026-08-17 ~20:47 BRT). A Fase 0
  pede pico **e** fora de pico. Falta rodar `python scripts/probe_api.py`
  de novo num horário de pico (dia de semana, 7h–9h ou 17h–19h BRT) e
  comparar a contagem de veículos distintos e o tempo de resposta.
- Não testei o que acontece com a API fora do ar (não caiu durante a sondagem).

**Aceite da Fase 0 parcialmente cumprido:** `docs/api-sample.json` existe com
dados reais; todas as perguntas têm resposta, exceto a comparação pico ×
fora de pico, que depende de rodar o script de novo em outro horário.
