import "./style.css";
import { createMap, fitToBuses, setBuses } from "./map";
import { fetchBuses, type BusesResponse } from "./api";

const POLL_MS = 20_000;
const STORAGE_KEY = "formiga-bus:linha";

const map = createMap("map");
const statusBar = document.querySelector<HTMLDivElement>("#status-bar")!;
const filterInput = document.querySelector<HTMLInputElement>("#filter")!;
const filterClear = document.querySelector<HTMLButtonElement>("#filter-clear")!;
const emptyState = document.querySelector<HTMLDivElement>("#empty-state")!;

let currentLinha = localStorage.getItem(STORAGE_KEY) ?? "";
filterInput.value = currentLinha;
filterClear.hidden = currentLinha === "";

let inFlight: AbortController | null = null;
let pollTimer: number | undefined;
let debounceTimer: number | undefined;

map.on("load", () => load(true));

async function load(fit: boolean): Promise<void> {
  inFlight?.abort();
  const controller = new AbortController();
  inFlight = controller;
  try {
    const data = await fetchBuses(currentLinha, controller.signal);
    setBuses(map, data);
    updateStatusBar(data);
    updateEmptyState(data);
    if (fit) fitToBuses(map, data);
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    statusBar.classList.add("stale");
    statusBar.innerHTML = `<span class="dot"></span>sem conexão`;
  }
}

function updateStatusBar(data: BusesResponse): void {
  statusBar.classList.toggle("stale", data.stale);
  const count = data.features.length;
  const age = data.age_s !== null ? Math.round(data.age_s) : null;
  const text =
    data.stale && data.fetched_at
      ? `sem conexão — posições de ${new Date(data.fetched_at).toLocaleTimeString("pt-BR", {
          hour: "2-digit",
          minute: "2-digit",
        })}`
      : `${count} ônibus · atualizado há ${age ?? "?"}s`;
  statusBar.innerHTML = `<span class="dot"></span>${text}`;
}

function updateEmptyState(data: BusesResponse): void {
  if (data.features.length > 0 || currentLinha === "") {
    emptyState.hidden = true;
    return;
  }
  emptyState.hidden = false;
  emptyState.innerHTML = `nenhum ônibus da linha ${currentLinha} transmitindo agora <button id="show-all">ver toda a frota</button>`;
  document.querySelector<HTMLButtonElement>("#show-all")?.addEventListener("click", () => setFilter(""));
}

function setFilter(linha: string): void {
  currentLinha = linha.trim();
  filterInput.value = currentLinha;
  filterClear.hidden = currentLinha === "";
  if (currentLinha) localStorage.setItem(STORAGE_KEY, currentLinha);
  else localStorage.removeItem(STORAGE_KEY);
  void load(true);
}

filterInput.addEventListener("input", () => {
  filterClear.hidden = filterInput.value === "";
  window.clearTimeout(debounceTimer);
  debounceTimer = window.setTimeout(() => setFilter(filterInput.value), 250);
});

filterClear.addEventListener("click", () => setFilter(""));

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    window.clearInterval(pollTimer);
  } else {
    void load(false);
    startPolling();
  }
});

function startPolling(): void {
  window.clearInterval(pollTimer);
  pollTimer = window.setInterval(() => void load(false), POLL_MS);
}

startPolling();
