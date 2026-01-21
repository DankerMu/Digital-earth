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

function isAbortError(error: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) return true;
  if (!isRecord(error)) return false;
  return error.name === 'AbortError';
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
  // CLDAS tiles are served in an XYZ-style scheme (y=0 at the north). If the backend ever
  // switches to a TMS (south-origin) scheme, use Cesium's `{reverseY}` placeholder instead.
  return `${origin}/api/v1/tiles/cldas/${timeKey}/${variable}/{z}/{x}/{y}.png`;
}

export function buildCldasTileUrl(options: CldasTileUrlTemplateOptions & { z: number; x: number; y: number }): string {
  const origin = resolveApiOrigin(options.apiBaseUrl);
  const timeKey = encodeURIComponent(options.timeKey);
  const variable = encodeURIComponent(options.variable);
  return `${origin}/api/v1/tiles/cldas/${timeKey}/${variable}/${options.z}/${options.x}/${options.y}.png`;
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

const CLDAS_TILE_PROBE_CACHE_MAX_ENTRIES = 200;
const CLDAS_TILE_PROBE_CACHE_TTL_MS = 5 * 60_000;

type CacheEntry<T> = { value: T; expiresAt: number };
const cldasTileProbeCache = new Map<string, CacheEntry<CldasTileProbeResult>>();

function readCache<T>(cache: Map<string, CacheEntry<T>>, key: string): T | undefined {
  const entry = cache.get(key);
  if (!entry) return undefined;
  if (Date.now() >= entry.expiresAt) {
    cache.delete(key);
    return undefined;
  }

  cache.delete(key);
  cache.set(key, entry);
  return entry.value;
}

function writeCache<T>(
  cache: Map<string, CacheEntry<T>>,
  key: string,
  value: T,
  options: { maxEntries: number; ttlMs: number },
) {
  const entry: CacheEntry<T> = { value, expiresAt: Date.now() + options.ttlMs };
  cache.delete(key);
  cache.set(key, entry);

  while (cache.size > options.maxEntries) {
    const oldest = cache.keys().next().value as string | undefined;
    if (!oldest) break;
    cache.delete(oldest);
  }
}

export type CldasTileProbeResult =
  | { status: 'available'; httpStatus: number }
  | { status: 'missing'; httpStatus: number }
  | { status: 'error'; httpStatus: number };

export function clearCldasTileProbeCache() {
  cldasTileProbeCache.clear();
}

export async function probeCldasTileAvailability(options: {
  apiBaseUrl: string;
  timeKey: string;
  variable: string;
  signal?: AbortSignal;
  cache?: 'default' | 'no-cache';
}): Promise<CldasTileProbeResult> {
  const url = buildCldasTileUrl({
    apiBaseUrl: options.apiBaseUrl,
    timeKey: options.timeKey,
    variable: options.variable,
    z: 0,
    x: 0,
    y: 0,
  });
  const key = url;

  const cached = options.cache !== 'no-cache' ? readCache(cldasTileProbeCache, key) : undefined;
  if (cached) return cached;

  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'image/png' },
      signal: options.signal,
      cache: options.cache === 'no-cache' ? 'no-store' : undefined,
    });

    const result: CldasTileProbeResult = response.ok
      ? { status: 'available', httpStatus: response.status }
      : response.status === 404
        ? { status: 'missing', httpStatus: response.status }
        : { status: 'error', httpStatus: response.status };

    if (options.cache !== 'no-cache') {
      writeCache(cldasTileProbeCache, key, result, {
        maxEntries: CLDAS_TILE_PROBE_CACHE_MAX_ENTRIES,
        ttlMs: CLDAS_TILE_PROBE_CACHE_TTL_MS,
      });
    }

    return result;
  } catch (error) {
    const result: CldasTileProbeResult = { status: 'error', httpStatus: 0 };
    if (isAbortError(error, options.signal)) {
      return result;
    }
    if (options.cache !== 'no-cache') {
      writeCache(cldasTileProbeCache, key, result, {
        maxEntries: CLDAS_TILE_PROBE_CACHE_MAX_ENTRIES,
        ttlMs: CLDAS_TILE_PROBE_CACHE_TTL_MS,
      });
    }
    return result;
  }
}
