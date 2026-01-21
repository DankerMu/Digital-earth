import type { CldasTileUrlTemplateOptions } from './types';

function resolveApiOrigin(apiBaseUrl: string): string {
  const trimmed = apiBaseUrl.trim();
  if (!trimmed) return window.location.origin;

  try {
    const url = new URL(trimmed, window.location.origin);
    return url.origin;
  } catch {
    return trimmed.replace(/\/+$/, '');
  }
}

export type WindVector = {
  lon: number;
  lat: number;
  u: number;
  v: number;
};

export type WindVectorData = {
  vectors: WindVector[];
};

export type WindVectorBBox = {
  west: number;
  south: number;
  east: number;
  north: number;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function normalizeDensity(value: number): number {
  if (!Number.isFinite(value)) return 10;
  const rounded = Math.round(value);
  if (rounded < 1) return 1;
  if (rounded > 100) return 100;
  return rounded;
}

function normalizeBBox(bbox: WindVectorBBox): WindVectorBBox {
  const { west, south, east, north } = bbox;
  if (![west, south, east, north].every((item) => Number.isFinite(item))) {
    throw new Error('Invalid bbox');
  }
  return { west, south, east, north };
}

function parseWindVectorData(payload: unknown): WindVectorData {
  if (!isRecord(payload)) return { vectors: [] };
  const rawVectors = payload.vectors;
  if (!Array.isArray(rawVectors)) return { vectors: [] };

  const vectors: WindVector[] = [];
  for (const entry of rawVectors) {
    if (!isRecord(entry)) continue;
    const lon = entry.lon;
    const lat = entry.lat;
    const u = entry.u;
    const v = entry.v;
    if (!isFiniteNumber(lon) || !isFiniteNumber(lat) || !isFiniteNumber(u) || !isFiniteNumber(v)) {
      continue;
    }
    vectors.push({ lon, lat, u, v });
  }

  return { vectors };
}

export async function fetchWindVectorData(options: {
  apiBaseUrl: string;
  timeKey: string;
  bbox: WindVectorBBox;
  density: number;
  signal?: AbortSignal;
}): Promise<WindVectorData> {
  const origin = resolveApiOrigin(options.apiBaseUrl);
  const timeKey = encodeURIComponent(options.timeKey);
  const bbox = normalizeBBox(options.bbox);
  const density = normalizeDensity(options.density);

  const url = `${origin}/api/v1/vectors/cldas/${timeKey}/wind?bbox=${bbox.west},${bbox.south},${bbox.east},${bbox.north}&density=${density}`;

  const response = await fetch(url, { signal: options.signal });
  if (!response.ok) {
    throw new Error(`Failed to fetch wind vectors: ${response.status}`);
  }

  const payload = (await response.json()) as unknown;
  return parseWindVectorData(payload);
}

export function buildCldasTileUrlTemplate(options: CldasTileUrlTemplateOptions): string {
  const origin = resolveApiOrigin(options.apiBaseUrl);
  const timeKey = encodeURIComponent(options.timeKey);
  const variable = encodeURIComponent(options.variable);
  return `${origin}/api/v1/tiles/cldas/${timeKey}/${variable}/{z}/{x}/{y}.png`;
}

export type PrecipitationTileUrlTemplateOptions = Omit<
  CldasTileUrlTemplateOptions,
  'variable'
> & {
  threshold?: number | null;
};

export function buildPrecipitationTileUrlTemplate(
  options: PrecipitationTileUrlTemplateOptions,
): string {
  const origin = resolveApiOrigin(options.apiBaseUrl);
  const timeKey = encodeURIComponent(options.timeKey);
  const base = `${origin}/api/v1/tiles/cldas/${timeKey}/precipitation/{z}/{x}/{y}.png`;

  if (options.threshold == null) return base;
  if (!Number.isFinite(options.threshold)) return base;

  return `${base}?threshold=${encodeURIComponent(String(options.threshold))}`;
}

function normalizeCloudVariable(variable: string | undefined): string {
  const trimmed = variable?.trim() ?? '';
  if (!trimmed) return 'TCC';

  const normalized = trimmed.toLowerCase();
  if (
    normalized === 'tcc' ||
    normalized === 'cloud' ||
    normalized === 'total_cloud_cover' ||
    normalized === 'total-cloud-cover' ||
    normalized === 'total cloud cover' ||
    normalized === 'total_cloud' ||
    normalized === 'total-cloud'
  ) {
    return 'TCC';
  }

  return trimmed.toUpperCase();
}

export type CloudTileUrlTemplateOptions = Omit<CldasTileUrlTemplateOptions, 'variable'> & {
  variable?: string;
};

export function buildCloudTileUrlTemplate(options: CloudTileUrlTemplateOptions): string {
  return buildCldasTileUrlTemplate({
    apiBaseUrl: options.apiBaseUrl,
    timeKey: options.timeKey,
    variable: normalizeCloudVariable(options.variable),
  });
}
