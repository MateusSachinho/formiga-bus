import { AttributionControl, GeoJSONSource, LngLatBounds, MapLibreMap, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { BusesResponse } from "./api";

// A detecção automática do worker do maplibre-gl quebra em dev e em build (pending pra
// sempre). Um `?url` no worker também não bastava: esse arquivo faz `import` de um
// "maplibre-gl-shared.mjs" irmão que o Vite não empacota junto por trás de um `?url`
// (é copiado cru, sem analisar os imports internos). Copiei os dois pra public/maplibre/
// e aponto direto pro arquivo estático — sem depender de nenhuma mágica de bundler.
// Se atualizar a versão do maplibre-gl, recopiar de node_modules/maplibre-gl/dist/.
// Ver docs/decisions.md.
setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

const RIO_CENTER: [number, number] = [-43.1729, -22.9068];
// MapLibre não substitui o token {r} (é uma convenção do Leaflet, não do TileJSON);
// usar {z}/{x}/{y} liso evita pedir um arquivo com "{r}" literal no nome.
const CARTO_DARK = [
  "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
  "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
  "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
  "https://d.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
];

export function createMap(container: string | HTMLElement): MapLibreMap {
  return new MapLibreMap({
    container,
    center: RIO_CENTER,
    zoom: 11,
    attributionControl: false,
    style: {
      version: 8,
      sources: {
        basemap: {
          type: "raster",
          tiles: CARTO_DARK,
          tileSize: 256,
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        },
        buses: { type: "geojson", data: { type: "FeatureCollection", features: [] } },
      },
      layers: [
        { id: "basemap", type: "raster", source: "basemap" },
        {
          id: "buses",
          type: "circle",
          source: "buses",
          paint: {
            "circle-color": "#2E7BFF",
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 2.5, 13, 5, 16, 8],
            "circle-opacity": 0.92,
            "circle-stroke-width": 1,
            "circle-stroke-color": "#7FB3FF",
            "circle-stroke-opacity": 0.35,
          },
        },
      ],
    },
  }).addControl(new AttributionControl({ compact: true }));
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
