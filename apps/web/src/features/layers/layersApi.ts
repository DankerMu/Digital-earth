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

type TileImageFormat = 'png' | 'webp';

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

function densityToStride(density: number): number {
  const normalized = normalizeDensity(density);
  const stride = Math.round(256 / normalized);
  if (!Number.isFinite(stride)) return 16;
  if (stride < 1) return 1;
  if (stride > 256) return 256;
  return stride;
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
  runTimeKey?: string;
  timeKey: string;
  level?: string;
  bbox: WindVectorBBox;
  density: number;
  signal?: AbortSignal;
}): Promise<WindVectorData> {
  const origin = resolveApiOrigin(options.apiBaseUrl);
  const runTimeKey = encodeURIComponent((options.runTimeKey ?? options.timeKey).trim());
  const timeKey = encodeURIComponent(options.timeKey.trim());
  const level = encodeURIComponent((options.level ?? 'sfc').trim() || 'sfc');
  const bbox = normalizeBBox(options.bbox);
  const stride = densityToStride(options.density);

  const baseUrl = `${origin}/api/v1/vector/ecmwf/${runTimeKey}/wind/${level}/${timeKey}?bbox=${bbox.west},${bbox.south},${bbox.east},${bbox.north}`;

  let response: Response | null = null;
  let candidateStride = stride;

  for (let attempt = 0; attempt < 4; attempt += 1) {
    response = await fetch(`${baseUrl}&stride=${candidateStride}`, { signal: options.signal });
    if (response.ok) break;
    if (response.status !== 400 || candidateStride >= 256) break;
    candidateStride = Math.min(256, candidateStride * 2);
  }

  if (!response || !response.ok) throw new Error(`Failed to fetch wind vectors: ${response?.status ?? 0}`);

  const payload = (await response.json()) as unknown;
  const parsed = parseWindVectorData(payload);
  if (parsed.vectors.length > 0) return parsed;

  if (!isRecord(payload)) return { vectors: [] };
  const uRaw = payload.u;
  const vRaw = payload.v;
  const latRaw = payload.lat;
  const lonRaw = payload.lon;

  if (!Array.isArray(uRaw) || !Array.isArray(vRaw) || !Array.isArray(latRaw) || !Array.isArray(lonRaw)) {
    return { vectors: [] };
  }

  const count = Math.min(uRaw.length, vRaw.length, latRaw.length, lonRaw.length);
  const vectors: WindVector[] = [];
  for (let index = 0; index < count; index += 1) {
    const u = uRaw[index];
    const v = vRaw[index];
    const lat = latRaw[index];
    const lon = lonRaw[index];
    if (!isFiniteNumber(lon) || !isFiniteNumber(lat) || !isFiniteNumber(u) || !isFiniteNumber(v)) {
      continue;
    }
    vectors.push({ lon, lat, u, v });
  }

  return { vectors };
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

function normalizeEcmwfTimeKey(timeKey: string): string {
  const trimmed = timeKey.trim();
  if (!trimmed) return '';
  if (/^\d{8}T\d{6}Z$/.test(trimmed)) return trimmed;
  if (/^\d{10}$/.test(trimmed)) {
    const year = trimmed.slice(0, 4);
    const month = trimmed.slice(4, 6);
    const day = trimmed.slice(6, 8);
    const hour = trimmed.slice(8, 10);
    return `${year}${month}${day}T${hour}0000Z`;
  }

  const parsed = new Date(trimmed);
  if (Number.isNaN(parsed.getTime())) return trimmed;

  const iso = parsed.toISOString().replace(/\.\d{3}Z$/, 'Z');
  return iso.replaceAll('-', '').replaceAll(':', '');
}

function encodeTileLayerPath(layer: string): string {
  return layer
    .trim()
    .replace(/^\/+/, '')
    .replace(/\/+$/, '')
    .split('/')
    .filter((segment) => segment.length > 0)
    .map((segment) => encodeURIComponent(segment))
    .join('/');
}

export type EcmwfTileUrlTemplateOptions = {
  apiBaseUrl: string;
  tileLayer: string;
  timeKey: string;
  level?: string;
  format?: TileImageFormat;
};

export function buildEcmwfTileUrlTemplate(options: EcmwfTileUrlTemplateOptions): string {
  const origin = resolveApiOrigin(options.apiBaseUrl);
  const layer = encodeTileLayerPath(options.tileLayer);
  const timeKey = encodeURIComponent(normalizeEcmwfTimeKey(options.timeKey));
  const level = encodeURIComponent((options.level ?? 'sfc').trim() || 'sfc');
  const format = options.format ?? 'png';

  return `${origin}/api/v1/tiles/${layer}/${timeKey}/${level}/{z}/{x}/{y}.${format}`;
}

export type EcmwfTemperatureTileUrlTemplateOptions = Omit<
  EcmwfTileUrlTemplateOptions,
  'tileLayer' | 'format'
> & {
  format?: TileImageFormat;
};

export function buildEcmwfTemperatureTileUrlTemplate(
  options: EcmwfTemperatureTileUrlTemplateOptions,
): string {
  return buildEcmwfTileUrlTemplate({
    apiBaseUrl: options.apiBaseUrl,
    tileLayer: 'ecmwf/temp',
    timeKey: options.timeKey,
    level: options.level,
    format: options.format,
  });
}

export type EcmwfCloudTileUrlTemplateOptions = Omit<
  EcmwfTileUrlTemplateOptions,
  'tileLayer' | 'format'
> & {
  format?: TileImageFormat;
};

export function buildEcmwfCloudTileUrlTemplate(options: EcmwfCloudTileUrlTemplateOptions): string {
  return buildEcmwfTileUrlTemplate({
    apiBaseUrl: options.apiBaseUrl,
    tileLayer: 'ecmwf/tcc',
    timeKey: options.timeKey,
    level: options.level ?? 'sfc',
    format: options.format,
  });
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
  const base = buildEcmwfTileUrlTemplate({
    apiBaseUrl: options.apiBaseUrl,
    tileLayer: 'ecmwf/precip_amount',
    timeKey: options.timeKey,
    level: 'sfc',
    format: 'png',
  });

  if (options.threshold == null) return base;
  if (!Number.isFinite(options.threshold)) return base;

  return `${base}?threshold=${encodeURIComponent(String(options.threshold))}`;
}

export type CloudTileUrlTemplateOptions = Omit<CldasTileUrlTemplateOptions, 'variable'> & {
  variable?: string;
};

export function buildCloudTileUrlTemplate(options: CloudTileUrlTemplateOptions): string {
  return buildEcmwfCloudTileUrlTemplate({
    apiBaseUrl: options.apiBaseUrl,
    timeKey: options.timeKey,
    level: 'sfc',
    format: 'png',
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
