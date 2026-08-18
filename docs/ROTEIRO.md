# formiga-bus — Roteiro de implementação

> Documento de trabalho para o Claude Code. Ler inteiro antes de escrever a primeira linha de código.
> Cada fase tem critério de aceite. Não avançar de fase sem cumprir o critério e fazer commit.

---

## 0. Contexto

**Produto:** app mobile-first (PWA + APK Android) que mostra os ônibus do Rio de Janeiro se movendo num mapa escuro, em tempo real, com filtro por número da linha.

**Nome:** `formiga-bus`. A metáfora é literal e guia o design: a frota vista de cima é um formigueiro — pontinhos azuis andando em trilhas. Isso justifica pontos pequenos e densos em vez de ícones de ônibus, e justifica o movimento contínuo em vez de saltos.

**Referência:** `https://github.com/Eduardo-Peruzzo/streamlit-localizacao-onibus`
Aproveitar dela: a fonte de dados, o tratamento de lat/lon com vírgula, a conversão de timestamp Unix ms → America/Sao_Paulo, a ideia de dedup por `ordem` e a janela temporal curta.
**Descartar dela:** o Streamlit inteiro. Streamlit não serve para mobile nem empacota em APK, e o `@st.fragment(run_every)` re-renderiza o mapa do zero a cada ciclo (o mapa "pisca" e perde zoom/pan). A arquitetura aqui é outra.

### Requisitos obrigatórios do cliente
1. Dark mode como tema primário (não é um toggle secundário — é o padrão).
2. Ônibus aparecem como pontinhos azuis no mapa.
3. Carregamento automático dos dados novos, sem o usuário pedir.
4. Filtro por número da linha (ex.: `554`).
5. O nome é `formiga-bus` (repo, título, manifest, package name, splash).

---

## 1. Stack decidida

| Camada | Escolha | Por quê |
|---|---|---|
| Backend | Python 3.11 + FastAPI + httpx | Reaproveita a lógica de parsing da referência; precisa existir (ver abaixo) |
| Mapa | MapLibre GL JS | Open source, sem chave, e renderiza milhares de pontos em WebGL |
| Frontend | React 18 + TypeScript + Vite | Padrão, e o Capacitor empacota direto |
| APK | Capacitor 6 (`@capacitor/android`) | Envolve o mesmo build web; não precisa reescrever nada |
| Estado | Zustand (ou `useState` + context se ficar simples demais) | Sem Redux |
| Testes | pytest (backend), Vitest (frontend) | — |

### Por que existe um backend (não é opcional)
1. **CORS.** A API da prefeitura muito provavelmente não envia `Access-Control-Allow-Origin`. O navegador bloqueia o `fetch` direto. Confirmar na Fase 0 — mas assumir que precisa de proxy.
2. **Tamanho.** 5 minutos de posições de *toda* a frota do Rio são milhares de linhas, muitas por veículo. Enviar isso cru para um celular em 4G a cada 20s é inviável. O backend deduplica e devolve só a última posição de cada ônibus, em GeoJSON enxuto.
3. **Uma requisição para todos.** 200 usuários abertos = 200 chamadas na API pública, e você toma rate limit ou derruba a fonte. Com um poller único no servidor, é 1 chamada a cada 20s, independentemente do número de clientes.
4. **Resiliência.** Quando a API da prefeitura cai (e ela cai), o backend continua servindo o último snapshot bom marcado como `stale`, em vez de o app mostrar tela vazia.

---

## 2. Fonte de dados — o que já se sabe

```
GET https://dados.mobilidade.rio/gps/sppo?dataInicial=2026-08-17+14:20:00&dataFinal=2026-08-17+14:25:00
```

Retorna um array JSON. Campos observados no código de referência:

| Campo | Formato | Observação |
|---|---|---|
| `ordem` | string | Identificador único do veículo. É a chave de dedup. |
| `linha` | string | Número da linha. **Nem sempre é numérico** — existem `SN`, `LECD70`, `SP852`. O filtro não pode assumir dígitos. |
| `latitude` | string | **Vírgula decimal.** `"-22,90342"` → trocar por ponto antes do float. |
| `longitude` | string | Idem. |
| `velocidade` | número | km/h |
| `datahora` | Unix ms | |
| `datahoraenvio` | Unix ms, UTC | A referência usa este para exibição |
| `datahoraservidor` | Unix ms | Existe no payload; conferir o que significa |

**Cuidados conhecidos:**
- Timestamps são Unix em **milissegundos**, em UTC. Converter para `America/Sao_Paulo` na exibição.
- O `+` no parâmetro de data é o espaço codificado. Os `:` do horário devem ir codificados também — usar `urlencode`, não concatenação de string.
- A janela é relativa ao horário atual. Janela muito grande = resposta lenta e payload gigante.

---

## Fase 0 — Sondar a API antes de tudo

**Isto não é opcional e não pode ser pulado.** O roteiro foi escrito sem acesso de rede à API; tudo acima veio da leitura do código de referência e precisa ser confirmado contra a realidade.

Tarefas:
1. Escrever `scripts/probe_api.py`: faz um GET com janela de 2 minutos, salva a resposta crua em `docs/api-sample.json`, e imprime: status HTTP, tamanho em bytes, quantidade de registros, quantidade de `ordem` distintas, lista de chaves do primeiro objeto, e o range de `datahora`.
2. Rodar em pelo menos dois horários diferentes (pico e fora de pico) e anotar os números em `docs/api-notes.md`.
3. Testar explicitamente:
   - O endpoint aceita algum parâmetro de filtro por linha? (tentar `&linha=554`). Se aceitar, ótimo — reduz o payload na origem. Se ignorar, filtrar depois do fetch.
   - Quanto tempo demora a resposta para janelas de 1, 5 e 10 minutos.
   - Qual o menor `tempo` que ainda retorna a frota inteira (se a janela for curta demais, ônibus que não transmitiram no intervalo somem do mapa). **Achar esse ponto de equilíbrio é a decisão técnica mais importante do projeto.**
   - Se a resposta traz cabeçalho CORS.
   - Se aparecem `latitude`/`longitude` iguais a `0` ou nulos (lixo a filtrar).
4. Se a API estiver fora do ar ou com formato diferente do descrito: **parar, documentar em `docs/api-notes.md` e avisar o usuário antes de seguir.** Não inventar dados de mentira para "destravar".

**Aceite:** `docs/api-sample.json` existe com dados reais e `docs/api-notes.md` responde todas as perguntas acima.

---

## Fase 1 — Backend

Estrutura:

```
backend/
├── app/
│   ├── main.py          # FastAPI, CORS, lifespan que sobe o poller
│   ├── config.py        # env vars com defaults
│   ├── sppo_client.py   # GET na API + timeout + retry
│   ├── transform.py     # parse → dedup → GeoJSON  (funções puras)
│   ├── store.py         # snapshot em memória + task de polling
│   └── routes.py
├── tests/
│   ├── test_transform.py
│   └── fixtures/sample.json   # copiado de docs/api-sample.json
├── requirements.txt
└── Dockerfile
```

### `transform.py` — funções puras, 100% testáveis sem rede
- `parse_records(raw: list) -> list[Bus]`
  - lat/lon: `str.replace(",", ".")` → float; descartar registro se falhar, se for 0, ou se cair fora do bounding box do Rio (`lat -23.1..-22.7`, `lon -43.8..-43.1`).
  - timestamps ms → `datetime` aware em UTC.
  - descartar registros sem `ordem`.
- `latest_per_vehicle(buses) -> list[Bus]` — agrupa por `ordem`, mantém o maior `datahora`. Não confiar na ordem do array.
- `drop_stale(buses, max_age_s) -> list[Bus]` — descarta quem não transmite há mais de ~180s. Um ponto parado há 4 minutos no mapa é uma mentira para o usuário.
- `to_geojson(buses) -> dict` — `FeatureCollection` de `Point`. **Coordenadas arredondadas em 5 casas** (~1m de precisão; corta o payload quase pela metade). Properties: `id` (ordem), `linha`, `vel`, `ts` (epoch segundos, não string formatada — quem formata é o cliente).

### `store.py` — o poller
- Uma task assíncrona no `lifespan` que chama a API a cada `POLL_INTERVAL` (default 20s) e guarda o snapshot processado em memória.
- As rotas HTTP **nunca** chamam a API da prefeitura — só leem o snapshot. Assim a resposta ao app é instantânea sempre.
- Guardar junto: `fetched_at`, `source_ok: bool`, `error: str | None`.
- Backoff exponencial em erro (20s → 40s → 80s, teto 120s), voltando ao normal no primeiro sucesso. Nunca apagar o último snapshot bom.
- Índice auxiliar: `dict[linha, list[Bus]]` para o filtro sair em O(1).

### Rotas (`/api/v1`)

| Rota | Retorno |
|---|---|
| `GET /buses?linha=554` | GeoJSON. `linha` opcional; **match por prefixo, case-insensitive**, para `55` já mostrar `554`, `553`. |
| `GET /lines` | `[{ "linha": "554", "count": 12 }, ...]` ordenado por linha, para autocomplete e sugestões. |
| `GET /bus/{ordem}/track?minutes=30` | LineString com o trajeto recente do veículo. Este endpoint **pode** chamar a API sob demanda (janela maior), com cache próprio de 60s por `ordem`. |
| `GET /health` | `{ status, fetched_at, age_s, vehicles, source_ok }` |

Toda resposta de dados carrega envelope com `fetched_at`, `age_s` e `stale: bool` (`stale = age_s > 90`). O app usa isso para o aviso de conexão.

Ativar GZip (`GZipMiddleware`) e CORS com origens vindas de env var.

**Aceite:** `pytest` verde usando a fixture real; `curl "localhost:8000/api/v1/buses?linha=554"` responde em <100ms com GeoJSON válido; derrubar a rede e ver a API continuar servindo com `stale: true`.

---

## Fase 2 — Design system

Antes de qualquer componente, criar `app/src/theme/tokens.css`. Nada de cor solta no código depois disso.

O brief fixa dois eixos — fundo escuro e pontos azuis — então a personalidade tem que vir do resto: da tipografia e do comportamento, não de mais cor.

**Paleta**

```css
--void:      #0A0D13;  /* fundo do mapa e do app; azul-preto, não preto puro */
--surface:   #131820;  /* painéis, sheet, campo de busca */
--surface-2: #1C232E;  /* estado pressionado, chips */
--hairline:  #29323F;  /* divisores de 1px */
--ink:       #E8ECF3;  /* texto primário */
--ink-dim:   #7E889B;  /* rótulos, metadados */
--bus:       #2E7BFF;  /* o pontinho azul */
--bus-glow:  #7FB3FF;  /* halo do ponto e estado selecionado */
--warn:      #FF8A4C;  /* dados velhos / sem conexão */
--live:      #3DD9A4;  /* pulso de "recebendo dados" */
```

Fundo `#0A0D13` e não `#000`: preto puro achata a hierarquia e faz o mapa escuro brigar com a UI escura. E o azul do ônibus precisa de um fundo levemente azulado para não parecer um adesivo colado.

**Tipografia** — três papéis, três funções reais:
- **Display** (`Bricolage Grotesque`, peso 600): só no título e nos números grandes. Usar com parcimônia.
- **Corpo** (`Inter`): rótulos, textos de estado, botões.
- **Dados** (`IBM Plex Mono`): números de linha, velocidade, horários. Número de linha é *código*, não palavra — mono é o correto: alinha em lista, não muda de largura quando o valor troca, e `554` fica visualmente distinto de texto comum.

Escala: 32 / 22 / 16 / 14 / 12. Espaçamento em múltiplos de 4.

**Elemento assinatura: os pontos não teleportam.**
Quando chega um snapshot novo, cada ônibus **interpola** da posição anterior para a nova ao longo de ~900ms com easing suave. É o que transforma "um gráfico que atualiza" em "um formigueiro andando" — e é a única coisa que precisa parecer cara. Todo o resto fica quieto: sem gradientes, sem sombras coloridas, sem glassmorphism, sem cards flutuando à toa.

Respeitar `prefers-reduced-motion`: com ele ativo, os pontos saltam direto para a posição nova.

**Voz da interface:** frases curtas, minúsculas depois da primeira letra, sem exclamação, sem emoji na UI. Estados vazios dizem o que fazer, não pedem desculpa.
- Vazio: `nenhum ônibus da linha 554 transmitindo agora` + botão `ver toda a frota`
- Offline: `sem conexão — posições de 14:32`
- Carregando: `procurando ônibus…`

---

## Fase 3 — Mapa

Arquivos: `src/map/MapView.tsx`, `src/map/darkStyle.ts`, `src/map/busLayer.ts`, `src/map/interpolate.ts`

**Basemap escuro.** Usar CARTO `dark_matter` (raster, sem chave de API):
`https://{a-d}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png`
A atribuição de OpenStreetMap e CARTO é obrigatória e tem que estar visível — coloque no rodapé do mapa, discreta mas presente. Se preferir vetor (melhor para zoom e rotação), avaliar Protomaps com estilo dark; documentar a escolha em `docs/decisions.md`.

**Camada dos ônibus — `circle`, nunca `Marker`.**
Um `maplibregl.Marker` por ônibus cria um nó DOM por veículo; com 3.000+ ônibus o celular trava. Usar uma única fonte GeoJSON com uma `circle-layer`:

```js
{
  id: 'buses',
  type: 'circle',
  source: 'buses',
  paint: {
    'circle-color': '#2E7BFF',
    'circle-radius': ['interpolate', ['linear'], ['zoom'], 9, 2.5, 13, 5, 16, 8],
    'circle-opacity': 0.92,
    'circle-stroke-width': 1,
    'circle-stroke-color': '#7FB3FF',
    'circle-stroke-opacity': 0.35,
  }
}
```

Raio variando com o zoom é o que evita a mancha azul única quando se vê a cidade inteira.

**Interpolação (`interpolate.ts`).** Manter um `Map<ordem, {from, to, startedAt}>`. Um `requestAnimationFrame` calcula as posições intermediárias e chama `source.setData()`. Pontos novos entram com fade-in; pontos que sumiram do snapshot saem com fade-out de 400ms em vez de piscar. Cortar o rAF quando a aba está oculta.

**Estado inicial:** centro no Rio (`-22.9068, -43.1729`), zoom 11.

**Toque num ponto:** bottom sheet com `linha` (grande, mono), `ordem`, velocidade, "atualizado há Xs" e um botão `ver trajeto` que chama `/bus/{ordem}/track` e desenha uma linha no mapa.

**Aceite:** com a frota inteira carregada, o mapa faz pan e zoom a 60fps num Android médio; ao chegar um snapshot novo os pontos deslizam, e o zoom/pan do usuário **não** é resetado.

---

## Fase 4 — Atualização automática

`src/hooks/useBusFeed.ts`

- Poll a cada 20s (alinhado ao poller do backend).
- **Pausar quando não está visível.** `document.visibilitychange` + eventos de `resume`/`pause` do Capacitor. App em segundo plano não gasta bateria nem dados. Ao voltar: buscar imediatamente, sem esperar o timer.
- Backoff em erro: 20 → 40 → 80s, teto 120s. Voltar a 20s no primeiro sucesso.
- `AbortController` para cancelar requisição em voo quando o filtro muda.
- Nunca substituir dados bons por um erro: em falha, manter o último snapshot e ligar o aviso.

**Barra de status** (fina, topo, sobre o mapa): `1.284 ônibus · atualizado há 6s`. Um ponto `--live` pulsa uma vez a cada chegada de snapshot — é o único feedback de "está vivo" necessário. Se `stale`, a barra troca para `--warn` com o horário do último dado.

Sem botão de refresh manual visível por padrão; puxar para atualizar (pull-to-refresh) resolve para quem quiser forçar.

---

## Fase 5 — Filtro por linha

`src/components/LineFilter.tsx`

- Campo de busca fixo no topo. `type="search"`, `inputMode="text"` — **não** forçar teclado numérico, porque existem linhas como `SN` e `LECD70`. `autocomplete="off"`, `enterkeyhint="search"`.
- Debounce de 250ms.
- Match por **prefixo**, case-insensitive: digitar `55` já mostra `554`, `553`, `557`.
- Filtrar **na hora, no snapshot local** (resposta instantânea, sem esperar rede) e mandar o parâmetro `linha` no próximo poll (payload menor). As duas coisas, não uma ou outra.
- Sugestões vindas de `/lines`: ao focar o campo, mostrar as linhas ativas com contagem de veículos. Digitou `55`, aparece `554 · 12 ônibus`.
- Com filtro ativo: `fitBounds` nos ônibus daquela linha, com padding e limite de zoom máximo 14. Se só existe 1 ônibus, centralizar sem dar zoom absurdo.
- Chip visível mostrando o filtro ativo, com `×` para limpar.
- **Persistir a última linha buscada** em `localStorage` e restaurar ao abrir — quem usa o app usa quase sempre a mesma linha. Isso é o que faz o app virar hábito.
- Vazio: `nenhum ônibus da linha 554 transmitindo agora` + `ver toda a frota`.

**Aceite:** digitar `554` filtra em menos de 100ms, o mapa enquadra os veículos, e fechar/reabrir o app volta com `554` já aplicado.

---

## Fase 6 — PWA e APK

**PWA**
- `manifest.webmanifest`: `name: "formiga-bus"`, `short_name: "formiga-bus"`, `theme_color: "#0A0D13"`, `background_color: "#0A0D13"`, `display: "standalone"`, `orientation: "portrait"`, ícones 192/512 + maskable.
- Service worker (`vite-plugin-pwa`): cachear o shell do app. **Não cachear as respostas de `/buses`** — dado de posição em cache é dado errado.
- `<meta name="color-scheme" content="dark">` e `theme-color` para a barra do sistema.
- `viewport-fit=cover` + `env(safe-area-inset-*)` no padding, senão a UI some atrás do notch.

**APK (Capacitor)**
```bash
npm i @capacitor/core @capacitor/cli @capacitor/android
npx cap init "formiga-bus" "br.formigabus.app" --web-dir=dist
npm run build && npx cap add android && npx cap sync
npx cap open android      # ou: cd android && ./gradlew assembleDebug
```
- `capacitor.config.ts`: `server.androidScheme: 'https'`, `backgroundColor: '#0A0D13'`.
- Permissões no `AndroidManifest.xml`: `INTERNET` (obrigatória). `ACCESS_FINE_LOCATION` **só** se a Fase 7 for feita.
- Splash e ícone adaptativo na paleta escura.
- O backend precisa estar num host público com HTTPS para o APK funcionar fora da sua rede. Documentar a variável `VITE_API_BASE`.

**Aceite:** `app-debug.apk` instala num Android real, abre em modo escuro, carrega ônibus e filtra por linha.

---

## Fase 7 — Opcionais (só depois que o resto estiver pronto)

Não começar nada daqui antes das Fases 0–6 estarem fechadas.
- Botão "onde estou" — centraliza no usuário. Pede permissão só ao toque, nunca no primeiro carregamento.
- Favoritar linhas (chips fixos abaixo da busca).
- Filtro por velocidade / destacar ônibus parados.
- Contagem de ônibus por linha num painel.
- Endpoint de BRT (a prefeitura expõe outros endpoints além do `/gps/sppo` — checar em `dados.mobilidade.rio`).

---

## 3. Estrutura final do repositório

```
formiga-bus/
├── README.md                 # o que é, como rodar, print
├── docs/
│   ├── ROTEIRO.md            # este arquivo
│   ├── api-notes.md          # achados da Fase 0
│   ├── api-sample.json
│   └── decisions.md          # decisões técnicas e por quê
├── backend/                  # ver Fase 1
├── app/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── theme/tokens.css
│   │   ├── map/{MapView.tsx,darkStyle.ts,busLayer.ts,interpolate.ts}
│   │   ├── components/{LineFilter.tsx,StatusBar.tsx,BusSheet.tsx,EmptyState.tsx}
│   │   ├── hooks/{useBusFeed.ts,useVisibility.ts}
│   │   └── lib/{api.ts,types.ts}
│   ├── public/{manifest.webmanifest,icons/}
│   ├── capacitor.config.ts
│   └── package.json
├── scripts/probe_api.py
├── docker-compose.yml        # backend + nginx servindo o build
└── .env.example
```

---

## 4. Regras para o Claude Code

1. **Fase 0 primeiro, sempre.** Sem dados reais na mão, tudo o mais é chute.
2. **Commit por fase**, mensagem descritiva. Nada de um commit único no final.
3. **Não inventar dados.** Se a API não responder, dizer isso — não criar mock silencioso e seguir como se estivesse funcionando.
4. **Nada de segredo no repo.** Tudo por env var, com `.env.example` versionado.
5. **`transform.py` sem I/O.** Funções puras, entrada e saída explícitas, testáveis sem rede.
6. **Rodar num Android real ou no DevTools em modo mobile** antes de dizer que uma fase acabou. É um app mobile; testar só no desktop não conta.
7. **Sem cor solta.** Toda cor sai de `tokens.css`. Se precisar de uma cor nova, adicionar aos tokens com nome e justificativa.
8. **Registrar o que mudou de rumo** em `docs/decisions.md` — sobretudo se a Fase 0 contradisser algo deste roteiro. O roteiro perde para a realidade da API.

---

## 5. Riscos conhecidos

| Risco | Mitigação |
|---|---|
| API pública instável ou lenta | Poller com backoff + servir snapshot `stale` |
| Payload grande demais em 4G | Dedup no servidor, coords com 5 casas, gzip, filtro por linha na origem |
| Sem CORS na API | Backend proxy (já previsto) |
| Milhares de pontos travando o celular | Camada `circle` em WebGL, jamais `Marker` |
| Janela temporal curta esconde ônibus | Calibrar empiricamente na Fase 0 e deixar em env var |
| Formato do campo mudar sem aviso | Parsing defensivo: registro inválido é descartado, não derruba a requisição inteira |

---

