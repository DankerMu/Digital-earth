export type LonLat = { lon: number; lat: number };
export type PolygonLonLat = { outer: LonLat[]; holes: LonLat[][] };

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

function parseGeoJsonPosition(value: unknown): LonLat | null {
  if (!Array.isArray(value) || value.length < 2) return null;
  const lon = value[0];
  const lat = value[1];
  if (typeof lon !== 'number' || !Number.isFinite(lon)) return null;
  if (typeof lat !== 'number' || !Number.isFinite(lat)) return null;
  return { lon, lat };
}

function parseGeoJsonRing(value: unknown): LonLat[] | null {
  if (!Array.isArray(value)) return null;
  const positions: LonLat[] = [];
  for (const entry of value) {
    const parsed = parseGeoJsonPosition(entry);
    if (!parsed) continue;
    positions.push(parsed);
  }
  return positions.length >= 3 ? positions : null;
}

function parseGeoJsonPolygon(value: unknown): PolygonLonLat | null {
  if (!Array.isArray(value) || value.length === 0) return null;
  const rings = value
    .map(parseGeoJsonRing)
    .filter((ring): ring is LonLat[] => ring != null);
  if (rings.length === 0) return null;
  return { outer: rings[0]!, holes: rings.slice(1) };
}

export function extractGeoJsonPolygons(value: unknown): PolygonLonLat[] {
  if (!isRecord(value)) return [];
  const type = value.type;
  if (typeof type !== 'string') return [];

  if (type === 'Feature') {
    return extractGeoJsonPolygons(value.geometry);
  }

  if (type === 'FeatureCollection') {
    const features = value.features;
    if (!Array.isArray(features)) return [];
    return features.flatMap((feature) => extractGeoJsonPolygons(feature));
  }

  if (type === 'GeometryCollection') {
    const geoms = value.geometries;
    if (!Array.isArray(geoms)) return [];
    return geoms.flatMap((geom) => extractGeoJsonPolygons(geom));
  }

  if (type === 'Polygon') {
    const parsed = parseGeoJsonPolygon(value.coordinates);
    return parsed ? [parsed] : [];
  }

  if (type === 'MultiPolygon') {
    const raw = value.coordinates;
    if (!Array.isArray(raw)) return [];
    return raw
      .map(parseGeoJsonPolygon)
      .filter((polygon): polygon is PolygonLonLat => polygon != null);
  }

  return [];
}

