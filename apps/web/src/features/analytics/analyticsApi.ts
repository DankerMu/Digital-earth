import { fetchJson, isHttpError } from '../../lib/http';

export type TileTemplate = {
  template: string;
  legend: string;
};

export type HistoricalStatisticItem = {
  source: string;
  variable: string;
  window_kind: string;
  window_key: string;
  version: string;
  window_start: string;
  window_end: string;
  samples: number;
  dataset_path: string;
  metadata_path: string;
  tiles: Record<string, TileTemplate>;
};

export type HistoricalStatisticsResponse = {
  items: HistoricalStatisticItem[];
};

export type BiasTileSetItem = {
  layer: string;
  time_key: string;
  level_key: string;
  min_zoom: number;
  max_zoom: number;
  formats: string[];
  tile: TileTemplate;
};

export type BiasTileSetsResponse = {
  items: BiasTileSetItem[];
};

function normalizeApiBaseUrl(apiBaseUrl: string): string {
  return apiBaseUrl.trim().replace(/\/+$/, '');
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function parseTileTemplate(value: unknown): TileTemplate | null {
  if (!isRecord(value)) return null;
  const template = value.template;
  const legend = value.legend;
  if (!isNonEmptyString(template) || !isNonEmptyString(legend)) return null;
  return { template: template.trim(), legend: legend.trim() };
}

function parseHistoricalStatisticItem(value: unknown): HistoricalStatisticItem | null {
  if (!isRecord(value)) return null;

  const source = value.source;
  const variable = value.variable;
  const window_kind = value.window_kind;
  const window_key = value.window_key;
  const version = value.version;
  const window_start = value.window_start;
  const window_end = value.window_end;
  const samples = value.samples;
  const dataset_path = value.dataset_path;
  const metadata_path = value.metadata_path;

  if (
    !isNonEmptyString(source) ||
    !isNonEmptyString(variable) ||
    !isNonEmptyString(window_kind) ||
    !isNonEmptyString(window_key) ||
    !isNonEmptyString(version) ||
    !isNonEmptyString(window_start) ||
    !isNonEmptyString(window_end) ||
    typeof samples !== 'number' ||
    !Number.isFinite(samples) ||
    !isNonEmptyString(dataset_path) ||
    !isNonEmptyString(metadata_path)
  ) {
    return null;
  }

  const tiles: Record<string, TileTemplate> = {};
  const tilesRaw = value.tiles;
  if (isRecord(tilesRaw)) {
    for (const [key, entry] of Object.entries(tilesRaw)) {
      const parsed = parseTileTemplate(entry);
      if (!parsed) continue;
      tiles[key] = parsed;
    }
  }

  return {
    source: source.trim(),
    variable: variable.trim(),
    window_kind: window_kind.trim(),
    window_key: window_key.trim(),
    version: version.trim(),
    window_start: window_start.trim(),
    window_end: window_end.trim(),
    samples,
    dataset_path: dataset_path.trim(),
    metadata_path: metadata_path.trim(),
    tiles,
  };
}

function parseHistoricalStatisticsResponse(payload: unknown): HistoricalStatisticsResponse {
  if (!isRecord(payload)) return { items: [] };
  const rawItems = payload.items;
  if (!Array.isArray(rawItems)) return { items: [] };
  const items: HistoricalStatisticItem[] = [];
  for (const entry of rawItems) {
    const parsed = parseHistoricalStatisticItem(entry);
    if (!parsed) continue;
    items.push(parsed);
  }
  return { items };
}

function parseBiasTileSetItem(value: unknown): BiasTileSetItem | null {
  if (!isRecord(value)) return null;
  const layer = value.layer;
  const time_key = value.time_key;
  const level_key = value.level_key;
  const min_zoom = value.min_zoom;
  const max_zoom = value.max_zoom;
  const formatsRaw = value.formats;
  const tile = parseTileTemplate(value.tile);

  if (
    !isNonEmptyString(layer) ||
    !isNonEmptyString(time_key) ||
    !isNonEmptyString(level_key) ||
    typeof min_zoom !== 'number' ||
    !Number.isFinite(min_zoom) ||
    typeof max_zoom !== 'number' ||
    !Number.isFinite(max_zoom) ||
    !tile
  ) {
    return null;
  }

  const formats = Array.isArray(formatsRaw)
    ? formatsRaw
        .filter((fmt) => isNonEmptyString(fmt))
        .map((fmt) => fmt.trim().toLowerCase())
        .filter((fmt, index, all) => all.indexOf(fmt) === index)
    : [];

  return {
    layer: layer.trim(),
    time_key: time_key.trim(),
    level_key: level_key.trim(),
    min_zoom,
    max_zoom,
    formats,
    tile,
  };
}

function parseBiasTileSetsResponse(payload: unknown): BiasTileSetsResponse {
  if (!isRecord(payload)) return { items: [] };
  const rawItems = payload.items;
  if (!Array.isArray(rawItems)) return { items: [] };
  const items: BiasTileSetItem[] = [];
  for (const entry of rawItems) {
    const parsed = parseBiasTileSetItem(entry);
    if (!parsed) continue;
    items.push(parsed);
  }
  return { items };
}

type CacheEntry<T> = { value: T; expiresAt: number };

const CACHE_TTL_MS = 60_000;
const CACHE_MAX_ENTRIES = 20;

const historicalStatisticsCache = new Map<string, CacheEntry<HistoricalStatisticsResponse>>();
const biasTileSetsCache = new Map<string, CacheEntry<BiasTileSetsResponse>>();

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

function writeCache<T>(cache: Map<string, CacheEntry<T>>, key: string, value: T) {
  cache.delete(key);
  cache.set(key, { value, expiresAt: Date.now() + CACHE_TTL_MS });
  while (cache.size > CACHE_MAX_ENTRIES) {
    const oldest = cache.keys().next().value as string | undefined;
    if (!oldest) break;
    cache.delete(oldest);
  }
}

export function clearAnalyticsCache() {
  historicalStatisticsCache.clear();
  biasTileSetsCache.clear();
}

export async function fetchHistoricalStatistics(options: {
  apiBaseUrl: string;
  source?: string;
  variable?: string;
  window_kind?: string;
  version?: string;
  fmt?: string;
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
  cache?: 'default' | 'no-cache';
}): Promise<HistoricalStatisticsResponse> {
  const base = normalizeApiBaseUrl(options.apiBaseUrl);
  const url = new URL('/api/v1/analytics/historical/statistics', base);
  if (isNonEmptyString(options.source)) url.searchParams.set('source', options.source.trim());
  if (isNonEmptyString(options.variable)) url.searchParams.set('variable', options.variable.trim());
  if (isNonEmptyString(options.window_kind)) url.searchParams.set('window_kind', options.window_kind.trim());
  if (isNonEmptyString(options.version)) url.searchParams.set('version', options.version.trim());
  if (isNonEmptyString(options.fmt)) url.searchParams.set('fmt', options.fmt.trim());
  if (typeof options.limit === 'number' && Number.isFinite(options.limit)) {
    url.searchParams.set('limit', String(options.limit));
  }
  if (typeof options.offset === 'number' && Number.isFinite(options.offset)) {
    url.searchParams.set('offset', String(options.offset));
  }

  const key = url.toString();
  const cached =
    options.cache !== 'no-cache' ? readCache(historicalStatisticsCache, key) : undefined;
  if (cached) return cached;

  try {
    const payload = await fetchJson<unknown>(url.toString(), {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: options.signal,
      cache: options.cache === 'no-cache' ? 'no-store' : undefined,
    });
    const parsed = parseHistoricalStatisticsResponse(payload);
    writeCache(historicalStatisticsCache, key, parsed);
    return parsed;
  } catch (error) {
    if (isHttpError(error)) {
      throw new Error(`Failed to load historical statistics: ${error.status}`, {
        cause: error,
      });
    }
    throw error;
  }
}

export async function fetchBiasTileSets(options: {
  apiBaseUrl: string;
  layer?: string;
  fmt?: string;
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
  cache?: 'default' | 'no-cache';
}): Promise<BiasTileSetsResponse> {
  const base = normalizeApiBaseUrl(options.apiBaseUrl);
  const url = new URL('/api/v1/analytics/bias/tile-sets', base);
  if (isNonEmptyString(options.layer)) url.searchParams.set('layer', options.layer.trim());
  if (isNonEmptyString(options.fmt)) url.searchParams.set('fmt', options.fmt.trim());
  if (typeof options.limit === 'number' && Number.isFinite(options.limit)) {
    url.searchParams.set('limit', String(options.limit));
  }
  if (typeof options.offset === 'number' && Number.isFinite(options.offset)) {
    url.searchParams.set('offset', String(options.offset));
  }

  const key = url.toString();
  const cached = options.cache !== 'no-cache' ? readCache(biasTileSetsCache, key) : undefined;
  if (cached) return cached;

  try {
    const payload = await fetchJson<unknown>(url.toString(), {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: options.signal,
      cache: options.cache === 'no-cache' ? 'no-store' : undefined,
    });
    const parsed = parseBiasTileSetsResponse(payload);
    writeCache(biasTileSetsCache, key, parsed);
    return parsed;
  } catch (error) {
    if (isHttpError(error)) {
      throw new Error(`Failed to load bias tile sets: ${error.status}`, { cause: error });
    }
    throw error;
  }
}

