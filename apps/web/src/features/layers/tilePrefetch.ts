import { usePerformanceModeStore } from '../../state/performanceMode';

type NetworkInformationLike = {
  effectiveType?: string;
  saveData?: boolean;
};

type UrlTemplateTilingSchemeLike = {
  getNumberOfXTilesAtLevel?: (level: number) => number;
  getNumberOfYTilesAtLevel?: (level: number) => number;
};

type UrlTemplateProviderLike<TRequest = unknown, TImage = unknown> = {
  url?: string;
  tilingScheme?: UrlTemplateTilingSchemeLike;
  maximumLevel?: number;
  tileWidth?: number;
  tileHeight?: number;
  requestImage?: (x: number, y: number, level: number, request?: TRequest) => Promise<TImage> | undefined;
};

export type TilePrefetchConfig = {
  maxFrames: number;
  maxUrlsPerFrame: number;
  maxPrefetchPerFrame: number;
  maxQueueSize: number;
  maxConcurrentPrefetch: number;
  consecutiveErrorCooldownThreshold: number;
  errorCooldownMs: number;
};

const DEFAULT_TILE_PREFETCH_CONFIG: TilePrefetchConfig = {
  maxFrames: 8,
  maxUrlsPerFrame: 180,
  maxPrefetchPerFrame: 40,
  maxQueueSize: 160,
  maxConcurrentPrefetch: 4,
  consecutiveErrorCooldownThreshold: 3,
  errorCooldownMs: 30_000,
};

let config: TilePrefetchConfig = { ...DEFAULT_TILE_PREFETCH_CONFIG };

export type TilePrefetchStats = {
  requestCacheHits: number;
  requestCacheMisses: number;
  prefetchCacheHits: number;
  prefetchCacheMisses: number;
  prefetchQueued: number;
  prefetchSkipped: number;
  prefetchSuccess: number;
  prefetchError: number;
};

const stats: TilePrefetchStats = {
  requestCacheHits: 0,
  requestCacheMisses: 0,
  prefetchCacheHits: 0,
  prefetchCacheMisses: 0,
  prefetchQueued: 0,
  prefetchSkipped: 0,
  prefetchSuccess: 0,
  prefetchError: 0,
};

type FrameUrlCache = Map<string, Set<string>>;

const frameUrlCache: FrameUrlCache = new Map();
const urlPromiseCache = new Map<string, Promise<unknown>>();
const prefetchQueue: string[] = [];
const queuedUrls = new Set<string>();

let prefetchRunnerScheduled = false;
let prefetchInFlight = 0;
let consecutivePrefetchErrors = 0;
let prefetchCooldownUntil = 0;
let performanceModeCacheCleared = false;

function clampPositiveInt(value: number, fallback: number): number {
  if (!Number.isFinite(value)) return fallback;
  const rounded = Math.floor(value);
  return rounded > 0 ? rounded : fallback;
}

function safeTrim(value: string | null | undefined): string {
  return value?.trim() ?? '';
}

function touchMapEntry<K, V>(map: Map<K, V>, key: K): V | undefined {
  const existing = map.get(key);
  if (existing === undefined) return undefined;
  map.delete(key);
  map.set(key, existing);
  return existing;
}

function getNetworkInformation(): NetworkInformationLike | null {
  if (typeof navigator === 'undefined') return null;
  const connection = (navigator as unknown as { connection?: NetworkInformationLike }).connection;
  if (!connection || typeof connection !== 'object') return null;
  return connection;
}

function getLowBandwidthEffectiveType(connection: NetworkInformationLike | null): string | null {
  const effectiveType = safeTrim(connection?.effectiveType).toLowerCase();
  if (!effectiveType) return null;
  if (effectiveType === 'slow-2g' || effectiveType === '2g' || effectiveType === '3g') return effectiveType;
  return null;
}

function maybeClearCacheForPerformanceMode() {
  const lowModeEnabled = usePerformanceModeStore.getState().mode === 'low';
  if (!lowModeEnabled) {
    performanceModeCacheCleared = false;
    return;
  }

  if (performanceModeCacheCleared) return;
  clearTilePrefetchCache();
}

export function getTilePrefetchDisabledReason(): string | null {
  maybeClearCacheForPerformanceMode();
  if (usePerformanceModeStore.getState().mode === 'low') return 'performance-mode';
  if (typeof navigator !== 'undefined' && navigator.onLine === false) return 'offline';
  if (Date.now() < prefetchCooldownUntil) return 'cooldown';

  const connection = getNetworkInformation();
  if (connection?.saveData) return 'save-data';

  const lowBandwidthType = getLowBandwidthEffectiveType(connection);
  if (lowBandwidthType) return `low-bandwidth:${lowBandwidthType}`;

  return null;
}

export function canPrefetchTiles(): boolean {
  return getTilePrefetchDisabledReason() === null;
}

function buildTileUrlFromTemplate(options: {
  template: string;
  x: number;
  y: number;
  level: number;
  tilingScheme?: UrlTemplateTilingSchemeLike;
  maximumLevel?: number;
  tileWidth?: number;
  tileHeight?: number;
}): string {
  const template = options.template;
  const x = options.x;
  const y = options.y;
  const z = options.level;
  const tilingScheme = options.tilingScheme;

  const tilesX = tilingScheme?.getNumberOfXTilesAtLevel?.(z);
  const tilesY = tilingScheme?.getNumberOfYTilesAtLevel?.(z);
  const reverseX = typeof tilesX === 'number' && Number.isFinite(tilesX) ? tilesX - x - 1 : x;
  const reverseY = typeof tilesY === 'number' && Number.isFinite(tilesY) ? tilesY - y - 1 : y;
  const reverseZ =
    typeof options.maximumLevel === 'number' && Number.isFinite(options.maximumLevel)
      ? options.maximumLevel - z
      : z;

  const width = typeof options.tileWidth === 'number' ? options.tileWidth : undefined;
  const height = typeof options.tileHeight === 'number' ? options.tileHeight : undefined;

  return template.replace(/\{(\w+)\}/g, (match, key) => {
    switch (key) {
      case 'x':
        return String(x);
      case 'y':
        return String(y);
      case 'z':
        return String(z);
      case 'reverseX':
        return String(reverseX);
      case 'reverseY':
        return String(reverseY);
      case 'reverseZ':
        return String(reverseZ);
      case 'width':
        return width != null ? String(width) : match;
      case 'height':
        return height != null ? String(height) : match;
      default:
        return match;
    }
  });
}

function isUrlStillReferenced(url: string): boolean {
  for (const urls of frameUrlCache.values()) {
    if (urls.has(url)) return true;
  }
  return false;
}

function enforceFrameLimit() {
  while (frameUrlCache.size > config.maxFrames) {
    const oldest = frameUrlCache.keys().next().value as string | undefined;
    if (!oldest) break;
    const urls = frameUrlCache.get(oldest);
    frameUrlCache.delete(oldest);
    if (!urls) continue;
    for (const url of urls) {
      if (isUrlStillReferenced(url)) continue;
      urlPromiseCache.delete(url);
    }
  }
}

function recordTileUrl(frameKey: string, url: string) {
  const key = safeTrim(frameKey);
  const normalizedUrl = safeTrim(url);
  if (!key || !normalizedUrl) return;

  let urls = frameUrlCache.get(key);
  if (urls) {
    frameUrlCache.delete(key);
    frameUrlCache.set(key, urls);
  } else {
    urls = new Set<string>();
    frameUrlCache.set(key, urls);
  }

  if (urls.has(normalizedUrl)) {
    urls.delete(normalizedUrl);
  }
  urls.add(normalizedUrl);

  while (urls.size > config.maxUrlsPerFrame) {
    const oldestUrl = urls.values().next().value as string | undefined;
    if (!oldestUrl) break;
    urls.delete(oldestUrl);
    if (isUrlStillReferenced(oldestUrl)) continue;
    urlPromiseCache.delete(oldestUrl);
  }

  enforceFrameLimit();
}

function createImagePrefetchPromise(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.decoding = 'async';
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Failed to prefetch tile image: ${url}`));
    img.src = url;
  });
}

function schedulePrefetchRunner() {
  if (prefetchRunnerScheduled) return;
  prefetchRunnerScheduled = true;

  window.setTimeout(() => {
    prefetchRunnerScheduled = false;
    runPrefetchQueue();
  }, 0);
}

function runPrefetchQueue() {
  if (!canPrefetchTiles()) {
    prefetchQueue.length = 0;
    queuedUrls.clear();
    return;
  }

  while (prefetchInFlight < config.maxConcurrentPrefetch && prefetchQueue.length > 0) {
    const url = prefetchQueue.pop();
    if (!url) break;
    queuedUrls.delete(url);

    prefetchInFlight += 1;
    const promise = createImagePrefetchPromise(url)
      .then((image) => {
        consecutivePrefetchErrors = 0;
        stats.prefetchSuccess += 1;
        return image;
      })
      .catch((error) => {
        stats.prefetchError += 1;
        consecutivePrefetchErrors += 1;

        urlPromiseCache.delete(url);

        if (consecutivePrefetchErrors >= config.consecutiveErrorCooldownThreshold) {
          prefetchCooldownUntil = Date.now() + config.errorCooldownMs;
        }

        throw error;
      })
      .finally(() => {
        prefetchInFlight -= 1;
        schedulePrefetchRunner();
      });

    urlPromiseCache.set(url, promise);
    void promise.catch(() => undefined);
  }
}

export function rewriteTileUrlTimeKey(url: string, fromTimeKey: string, toTimeKey: string): string | null {
  const rawUrl = safeTrim(url);
  if (!rawUrl) return null;

  const fromEncoded = encodeURIComponent(fromTimeKey);
  const toEncoded = encodeURIComponent(toTimeKey);

  if (rawUrl.includes(`/${fromEncoded}/`)) {
    return rawUrl.replace(`/${fromEncoded}/`, `/${toEncoded}/`);
  }

  if (rawUrl.includes(fromEncoded)) {
    return rawUrl.replace(fromEncoded, toEncoded);
  }

  return null;
}

export function prefetchNextFrameTiles(options: {
  currentTimeKey: string;
  nextTimeKey: string;
  maxPrefetch?: number;
}) {
  if (!canPrefetchTiles()) {
    stats.prefetchSkipped += 1;
    return;
  }

  const currentTimeKey = safeTrim(options.currentTimeKey);
  const nextTimeKey = safeTrim(options.nextTimeKey);
  if (!currentTimeKey || !nextTimeKey) {
    stats.prefetchSkipped += 1;
    return;
  }

  const urls = frameUrlCache.get(currentTimeKey);
  if (!urls || urls.size === 0) {
    stats.prefetchSkipped += 1;
    return;
  }

  const limit = clampPositiveInt(options.maxPrefetch ?? config.maxPrefetchPerFrame, config.maxPrefetchPerFrame);
  let queued = 0;

  const urlList = Array.from(urls);
  for (let index = 0; index < urlList.length; index += 1) {
    if (queued >= limit) break;
    const url = urlList[index];
    if (!url) continue;
    const nextUrl = rewriteTileUrlTimeKey(url, currentTimeKey, nextTimeKey);
    if (!nextUrl) continue;

    recordTileUrl(nextTimeKey, nextUrl);

    if (touchMapEntry(urlPromiseCache, nextUrl)) {
      stats.prefetchCacheHits += 1;
      continue;
    }

    if (queuedUrls.has(nextUrl)) {
      stats.prefetchCacheHits += 1;
      continue;
    }

    if (prefetchQueue.length >= config.maxQueueSize) {
      const dropped = prefetchQueue.shift();
      if (dropped) {
        queuedUrls.delete(dropped);
        stats.prefetchSkipped += 1;
      } else {
        stats.prefetchSkipped += 1;
        break;
      }
    }

    stats.prefetchCacheMisses += 1;
    stats.prefetchQueued += 1;
    queuedUrls.add(nextUrl);
    prefetchQueue.push(nextUrl);
    queued += 1;
  }

  if (queued > 0) {
    schedulePrefetchRunner();
  }
}

const PROVIDER_PATCHED = Symbol.for('digital-earth.tile-prefetch.providerPatched');

export function attachTileCacheToProvider<TRequest, TImage>(
  provider: UrlTemplateProviderLike<TRequest, TImage>,
  options: { frameKey: string },
) {
  const frameKey = safeTrim(options.frameKey);
  if (!frameKey) return;
  if (!provider || typeof provider !== 'object') return;

  const originalRequestImage = provider.requestImage?.bind(provider);
  if (!originalRequestImage) return;

  if ((provider as unknown as Record<PropertyKey, unknown>)[PROVIDER_PATCHED]) return;
  (provider as unknown as Record<PropertyKey, unknown>)[PROVIDER_PATCHED] = true;

  provider.requestImage = (x, y, level, request) => {
    if (usePerformanceModeStore.getState().mode === 'low') {
      maybeClearCacheForPerformanceMode();
      return originalRequestImage(x, y, level, request);
    }

    const template = safeTrim(provider.url);
    const url = template
      ? buildTileUrlFromTemplate({
          template,
          x,
          y,
          level,
          tilingScheme: provider.tilingScheme,
          maximumLevel: provider.maximumLevel,
          tileWidth: provider.tileWidth,
          tileHeight: provider.tileHeight,
        })
      : null;

    if (url) {
      recordTileUrl(frameKey, url);
      const cached = touchMapEntry(urlPromiseCache, url);
      if (cached) {
        stats.requestCacheHits += 1;
        return cached as ReturnType<typeof originalRequestImage>;
      }
      stats.requestCacheMisses += 1;
    }

    const result = originalRequestImage(x, y, level, request);
    if (!url || !result) return result;

    const cachedPromise = Promise.resolve(result).catch((error) => {
      urlPromiseCache.delete(url);
      throw error;
    });
    urlPromiseCache.set(url, cachedPromise as Promise<unknown>);
    return cachedPromise;
  };
}

export function clearTilePrefetchCache() {
  frameUrlCache.clear();
  urlPromiseCache.clear();
  prefetchQueue.length = 0;
  queuedUrls.clear();
  consecutivePrefetchErrors = 0;
  prefetchCooldownUntil = 0;
  performanceModeCacheCleared = usePerformanceModeStore.getState().mode === 'low';
}

export function resetTilePrefetchStats() {
  stats.requestCacheHits = 0;
  stats.requestCacheMisses = 0;
  stats.prefetchCacheHits = 0;
  stats.prefetchCacheMisses = 0;
  stats.prefetchQueued = 0;
  stats.prefetchSkipped = 0;
  stats.prefetchSuccess = 0;
  stats.prefetchError = 0;
}

export function getTilePrefetchStats(): TilePrefetchStats & {
  framesTracked: number;
  urlsTracked: number;
} {
  return {
    ...stats,
    framesTracked: frameUrlCache.size,
    urlsTracked: urlPromiseCache.size,
  };
}

export function resetTilePrefetchConfig() {
  config = { ...DEFAULT_TILE_PREFETCH_CONFIG };
}

export function setTilePrefetchConfig(partial: Partial<TilePrefetchConfig>) {
  config = {
    ...config,
    ...partial,
    maxFrames: clampPositiveInt(partial.maxFrames ?? config.maxFrames, DEFAULT_TILE_PREFETCH_CONFIG.maxFrames),
    maxUrlsPerFrame: clampPositiveInt(
      partial.maxUrlsPerFrame ?? config.maxUrlsPerFrame,
      DEFAULT_TILE_PREFETCH_CONFIG.maxUrlsPerFrame,
    ),
    maxPrefetchPerFrame: clampPositiveInt(
      partial.maxPrefetchPerFrame ?? config.maxPrefetchPerFrame,
      DEFAULT_TILE_PREFETCH_CONFIG.maxPrefetchPerFrame,
    ),
    maxQueueSize: clampPositiveInt(partial.maxQueueSize ?? config.maxQueueSize, DEFAULT_TILE_PREFETCH_CONFIG.maxQueueSize),
    maxConcurrentPrefetch: clampPositiveInt(
      partial.maxConcurrentPrefetch ?? config.maxConcurrentPrefetch,
      DEFAULT_TILE_PREFETCH_CONFIG.maxConcurrentPrefetch,
    ),
    consecutiveErrorCooldownThreshold: clampPositiveInt(
      partial.consecutiveErrorCooldownThreshold ?? config.consecutiveErrorCooldownThreshold,
      DEFAULT_TILE_PREFETCH_CONFIG.consecutiveErrorCooldownThreshold,
    ),
    errorCooldownMs: clampPositiveInt(partial.errorCooldownMs ?? config.errorCooldownMs, DEFAULT_TILE_PREFETCH_CONFIG.errorCooldownMs),
  };
  enforceFrameLimit();
}
