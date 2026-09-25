import { AttributionControl, GeoJSONSource, LngLatBounds, MapLibreMap, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { BusesResponse } from "./api";

// A detecção automática do worker do maplibre-gl quebra em dev e em build (pending pra
// sempre). Um `?url` no worker também não bastava: esse arquivo faz `import` de um
// "maplibre-gl-shared.mjs" irmão que o Vite não empacota junto por trás de um `?url`
// (é copiado cru, sem analisar os imports internos). Copiei os dois pra public/maplibre/
// e aponto direto pro arquivo estático — sem depender de nenhuma mágica de bundler.
// Se atualizar a versão do maplibre-gl, recopiar de node_modules/maplibre-gl/dist/.
// Ver docs/decisions.md. Com basemap vetorial o worker virou crítico pro mapa INTEIRO
// (o raster antigo não dependia dele; só os pontos quebravam).
setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

const RIO_CENTER: [number, number] = [-43.1729, -22.9068];
// Dados OpenStreetMap, tiles vetoriais, sem chave e sem limite (openfreemap.org).
// Vetorial em vez de raster porque o alvo é celular: nítido em qualquer densidade de
// tela e zoom, com nome de rua e POI — o CARTO dark_all era 256px sem retina e
// minimalista de propósito, que foi exatamente a reclamação dos testadores.
const STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";

export function createMap(container: string | HTMLElement): MapLibreMap {
  return new MapLibreMap({
    container,
    center: RIO_CENTER,
    zoom: 11,
    attributionControl: false,
    style: STYLE_URL,
    // OpenFreeMap exige atribuição visível (OpenFreeMap / OpenMapTiles / OpenStreetMap)
    // e o estilo já a traz nas suas fontes. Canto superior direito porque no padrão
    // (inferior direito) a barra de busca cobre o controle — o canto de cima vagou
    // quando o slider de brilho saiu.
  }).addControl(new AttributionControl({ compact: true }), "top-right");
}

// Com style por URL não dá pra declarar a fonte/camada dos ônibus no construtor —
// o estilo só existe depois do `load`. Chamar uma vez, de dentro do `map.on("load")`.
export function addBusLayer(map: MapLibreMap): void {
  map.addSource("buses", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addLayer({
    id: "buses",
    type: "circle",
    source: "buses",
    paint: {
      "circle-color": "#2E7BFF",
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 2.5, 13, 5, 16, 8],
      "circle-opacity": 0.92,
      // Halo branco: sobre o basemap claro o ponto precisa se separar de ruas
      // coloridas. O stroke azul-claro antigo (0.35) só funcionava no fundo escuro.
      "circle-stroke-width": 1.5,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-opacity": 0.9,
    },
  });
}

export function setBuses(map: MapLibreMap, data: BusesResponse): void {
  const source = map.getSource("buses") as GeoJSONSource | undefined;
  // ponytail: setData troca os pontos direto, sem interpolar entre posições —
  // é o "salto" que o ROTEIRO queria animar. Adicionar depois com requestAnimationFrame
  // se o corte ficar feio na prática; por ora o mapa já não perde zoom/pan ao atualizar.
  source?.setData(data as any);
}

export function fitToBuses(map: MapLibreMap, data: BusesResponse): void {
  if (data.features.length === 0) return;
  if (data.features.length === 1) {
    map.flyTo({ center: data.features[0].geometry.coordinates, zoom: 14 });
    return;
  }
  const bounds = new LngLatBounds();
  for (const f of data.features) bounds.extend(f.geometry.coordinates);
  map.fitBounds(bounds, { padding: 48, maxZoom: 14, duration: 500 });
}
