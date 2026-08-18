export interface BusFeature {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: { id: string; linha: string; vel: number; ts: number };
}

export interface BusesResponse {
  type: "FeatureCollection";
  features: BusFeature[];
  fetched_at: string | null;
  age_s: number | null;
  stale: boolean;
}

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export async function fetchBuses(linha: string, signal?: AbortSignal): Promise<BusesResponse> {
  const url = new URL(`${API_BASE}/api/v1/buses`);
  if (linha) url.searchParams.set("linha", linha);
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`buses respondeu ${res.status}`);
  return res.json();
}
