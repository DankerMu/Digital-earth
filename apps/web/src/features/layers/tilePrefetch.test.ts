import { beforeEach, describe, expect, it, vi } from 'vitest';

import { usePerformanceModeStore } from '../../state/performanceMode';
import {
  attachTileCacheToProvider,
  canPrefetchTiles,
  clearTilePrefetchCache,
  getTilePrefetchDisabledReason,
  getTilePrefetchStats,
  prefetchNextFrameTiles,
  resetTilePrefetchConfig,
  resetTilePrefetchStats,
  rewriteTileUrlTimeKey,
  setTilePrefetchConfig,
} from './tilePrefetch';

class ImageStub {
  public decoding = 'async';
  public crossOrigin: string | null = null;
  public onload: (() => void) | null = null;
  public onerror: (() => void) | null = null;
  private _src = '';

  set src(value: string) {
    this._src = value;
    if (value.includes('fail')) {
      this.onerror?.();
      return;
    }
    this.onload?.();
  }

  get src() {
    return this._src;
  }
}

function setNavigatorConnection(value: unknown) {
  Object.defineProperty(navigator, 'connection', {
    configurable: true,
    value,
  });
}

function makeOkRequestImage() {
  return vi.fn((...args: unknown[]) => {
    void args;
    return Promise.resolve({ ok: true });
  });
}

function makeRejectedRequestImage(error: Error) {
  return vi.fn((...args: unknown[]) => {
    void args;
    return Promise.reject(error);
  });
}

describe('tilePrefetch', () => {
  beforeEach(() => {
    vi.stubGlobal('Image', ImageStub);
    usePerformanceModeStore.setState({ enabled: false });
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
    setNavigatorConnection({ effectiveType: '4g', saveData: false });
    resetTilePrefetchConfig();
    clearTilePrefetchCache();
    resetTilePrefetchStats();
  });

  it('rewrites encoded time keys in tile URLs', () => {
    const from = '2024-01-15T00:00:00Z';
    const to = '2024-01-15T01:00:00Z';
    const url = `https://api.test/api/v1/tiles/cldas/${encodeURIComponent(from)}/TMP/3/1/2.png`;

    expect(rewriteTileUrlTimeKey(url, from, to)).toBe(
      `https://api.test/api/v1/tiles/cldas/${encodeURIComponent(to)}/TMP/3/1/2.png`,
    );

    expect(rewriteTileUrlTimeKey(url, 'missing', to)).toBeNull();
    expect(rewriteTileUrlTimeKey('   ', from, to)).toBeNull();
  });

  it('rewrites time keys even when the encoded value is not path-delimited', () => {
    const from = '2024-01-15T00:00:00Z';
    const to = '2024-01-15T01:00:00Z';
    const url = `https://api.test/api/v1/tiles?time=${encodeURIComponent(from)}&v=TMP`;

    expect(rewriteTileUrlTimeKey(url, from, to)).toBe(
      `https://api.test/api/v1/tiles?time=${encodeURIComponent(to)}&v=TMP`,
    );
  });

  it('disables prefetch on low-bandwidth connections and performance mode', () => {
    setNavigatorConnection({ effectiveType: '3g', saveData: false });
    expect(getTilePrefetchDisabledReason()).toBe('low-bandwidth:3g');
    expect(canPrefetchTiles()).toBe(false);

    setNavigatorConnection({ effectiveType: '5g', saveData: false });
    expect(getTilePrefetchDisabledReason()).toBeNull();
    expect(canPrefetchTiles()).toBe(true);

    setNavigatorConnection({ effectiveType: '4g', saveData: true });
    expect(getTilePrefetchDisabledReason()).toBe('save-data');

    usePerformanceModeStore.setState({ enabled: true });
    expect(getTilePrefetchDisabledReason()).toBe('performance-mode');
  });

  it('reports offline when navigator is offline', () => {
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: false });
    expect(getTilePrefetchDisabledReason()).toBe('offline');
    expect(canPrefetchTiles()).toBe(false);
  });

  it('caches imagery provider requestImage calls and reports cache hits', async () => {
    const timeKey = '2024-01-15T00:00:00Z';
    const requestImage = makeOkRequestImage();
    const provider = {
      url: `https://api.test/api/v1/tiles/cldas/${encodeURIComponent(timeKey)}/TMP/{z}/{x}/{y}.png`,
      tilingScheme: {
        getNumberOfXTilesAtLevel: (level: number) => 1 << level,
        getNumberOfYTilesAtLevel: (level: number) => 1 << level,
      },
      tileWidth: 256,
      tileHeight: 256,
      maximumLevel: 22,
      requestImage,
    };

    attachTileCacheToProvider(provider, { frameKey: timeKey });

    await provider.requestImage(1, 2, 3);
    await provider.requestImage(1, 2, 3);

    expect(requestImage).toHaveBeenCalledTimes(1);
    expect(getTilePrefetchStats()).toMatchObject({
      requestCacheHits: 1,
      requestCacheMisses: 1,
      framesTracked: 1,
      urlsTracked: 1,
    });
  });

  it('skips caching when provider has no URL template', async () => {
    const requestImage = makeOkRequestImage();
    const provider = {
      url: '',
      requestImage,
    };

    attachTileCacheToProvider(provider, { frameKey: '2024-01-15T00:00:00Z' });

    await provider.requestImage(0, 0, 0);

    expect(requestImage).toHaveBeenCalledTimes(1);
    expect(getTilePrefetchStats()).toMatchObject({
      requestCacheHits: 0,
      requestCacheMisses: 0,
      framesTracked: 0,
      urlsTracked: 0,
    });
  });

  it('does not mark providers without requestImage as patched', async () => {
    const timeKey = '2024-01-15T00:00:00Z';
    const provider: { url: string; requestImage?: ReturnType<typeof makeOkRequestImage> } = {
      url: `https://api.test/api/v1/tiles/cldas/${encodeURIComponent(timeKey)}/TMP/{z}/{x}/{y}.png`,
    };

    attachTileCacheToProvider(provider, { frameKey: timeKey });

    const requestImage = makeOkRequestImage();
    provider.requestImage = requestImage;

    attachTileCacheToProvider(provider, { frameKey: timeKey });

    await provider.requestImage!(0, 0, 0);
    await provider.requestImage!(0, 0, 0);

    expect(requestImage).toHaveBeenCalledTimes(1);
  });

  it('disables and clears request caching in performance mode', async () => {
    const timeKey = '2024-01-15T00:00:00Z';
    const requestImage = makeOkRequestImage();
    const provider = {
      url: `https://api.test/api/v1/tiles/cldas/${encodeURIComponent(timeKey)}/TMP/{z}/{x}/{y}.png`,
      tilingScheme: {
        getNumberOfXTilesAtLevel: (level: number) => 1 << level,
        getNumberOfYTilesAtLevel: (level: number) => 1 << level,
      },
      requestImage,
    };

    attachTileCacheToProvider(provider, { frameKey: timeKey });

    await provider.requestImage(0, 0, 0);
    expect(getTilePrefetchStats()).toMatchObject({ urlsTracked: 1, framesTracked: 1 });

    usePerformanceModeStore.setState({ enabled: true });
    expect(getTilePrefetchDisabledReason()).toBe('performance-mode');
    expect(getTilePrefetchStats()).toMatchObject({ urlsTracked: 0, framesTracked: 0 });

    await provider.requestImage(0, 0, 0);
    await provider.requestImage(0, 0, 0);
    expect(requestImage).toHaveBeenCalledTimes(3);
    expect(getTilePrefetchStats()).toMatchObject({ urlsTracked: 0, framesTracked: 0 });
  });

  it('evicts old frames and urls based on maxFrames/maxUrlsPerFrame', async () => {
    setTilePrefetchConfig({ maxFrames: 1, maxUrlsPerFrame: 1 });

    const timeKey1 = '2024-01-15T00:00:00Z';
    const provider1 = {
      url: `https://api.test/tiles?time=${encodeURIComponent(timeKey1)}&z={reverseZ}&x={reverseX}&y={reverseY}&size={width}x{height}&unknown={foo}`,
      tilingScheme: {
        getNumberOfXTilesAtLevel: (level: number) => 1 << level,
        getNumberOfYTilesAtLevel: (level: number) => 1 << level,
      },
      maximumLevel: 10,
      tileWidth: 256,
      tileHeight: 256,
      requestImage: makeOkRequestImage(),
    };

    attachTileCacheToProvider(provider1, { frameKey: timeKey1 });
    await provider1.requestImage(0, 0, 2);
    await provider1.requestImage(1, 0, 2);

    const timeKey2 = '2024-01-15T01:00:00Z';
    const provider2 = {
      url: `https://api.test/tiles?time=${encodeURIComponent(timeKey2)}&z={z}&x={x}&y={y}`,
      tilingScheme: provider1.tilingScheme,
      requestImage: makeOkRequestImage(),
    };

    attachTileCacheToProvider(provider2, { frameKey: timeKey2 });
    await provider2.requestImage(0, 0, 0);

    expect(getTilePrefetchStats()).toMatchObject({
      framesTracked: 1,
      urlsTracked: 1,
    });
  });

  it('drops cached entries when requestImage rejects', async () => {
    const timeKey = '2024-01-15T00:00:00Z';
    const requestImage = makeRejectedRequestImage(new Error('boom'));
    const provider = {
      url: `https://api.test/api/v1/tiles/cldas/${encodeURIComponent(timeKey)}/TMP/{z}/{x}/{y}.png`,
      tilingScheme: {
        getNumberOfXTilesAtLevel: (level: number) => 1 << level,
        getNumberOfYTilesAtLevel: (level: number) => 1 << level,
      },
      requestImage,
    };

    attachTileCacheToProvider(provider, { frameKey: timeKey });

    await expect(provider.requestImage(0, 0, 0)).rejects.toThrow('boom');
    await expect(provider.requestImage(0, 0, 0)).rejects.toThrow('boom');

    expect(requestImage).toHaveBeenCalledTimes(2);
  });

  it('drops the oldest queued prefetch when the queue is full', async () => {
    vi.useFakeTimers();

    const prefetched: string[] = [];
    class RecordingImageStub {
      public decoding = 'async';
      public crossOrigin: string | null = null;
      public onload: (() => void) | null = null;
      public onerror: (() => void) | null = null;
      private _src = '';

      set src(value: string) {
        this._src = value;
        prefetched.push(value);
        this.onload?.();
      }

      get src() {
        return this._src;
      }
    }

    vi.stubGlobal('Image', RecordingImageStub);

    setTilePrefetchConfig({ maxQueueSize: 1, maxPrefetchPerFrame: 10 });

    const currentTimeKey = '2024-01-15T00:00:00Z';
    const nextTimeKey = '2024-01-15T01:00:00Z';

    const provider = {
      url: `https://api.test/api/v1/tiles/cldas/${encodeURIComponent(currentTimeKey)}/TMP/{z}/{x}/{y}.png`,
      tilingScheme: {
        getNumberOfXTilesAtLevel: (level: number) => 1 << level,
        getNumberOfYTilesAtLevel: (level: number) => 1 << level,
      },
      requestImage: makeOkRequestImage(),
    };

    attachTileCacheToProvider(provider, { frameKey: currentTimeKey });
    await provider.requestImage(0, 0, 0);
    await provider.requestImage(1, 0, 0);

    prefetchNextFrameTiles({ currentTimeKey, nextTimeKey });

    expect(getTilePrefetchStats().prefetchQueued).toBe(2);
    expect(getTilePrefetchStats().prefetchSkipped).toBe(1);

    await vi.runAllTimersAsync();
    expect(prefetched[0]).toContain(`/${encodeURIComponent(nextTimeKey)}/`);
    expect(prefetched[0]).toContain('/0/1/0.png');
    vi.useRealTimers();
  });

  it('prioritizes the most recent frame tiles when the prefetch queue is saturated', async () => {
    vi.useFakeTimers();

    const prefetched: string[] = [];
    class RecordingImageStub {
      public decoding = 'async';
      public crossOrigin: string | null = null;
      public onload: (() => void) | null = null;
      public onerror: (() => void) | null = null;
      private _src = '';

      set src(value: string) {
        this._src = value;
        prefetched.push(value);
        this.onload?.();
      }

      get src() {
        return this._src;
      }
    }

    vi.stubGlobal('Image', RecordingImageStub);

    setTilePrefetchConfig({ maxQueueSize: 2, maxPrefetchPerFrame: 2, maxConcurrentPrefetch: 1 });

    const timeKey0 = '2024-01-15T00:00:00Z';
    const timeKey1 = '2024-01-15T01:00:00Z';
    const timeKey2 = '2024-01-15T02:00:00Z';

    const provider = {
      url: `https://api.test/api/v1/tiles/cldas/${encodeURIComponent(timeKey0)}/TMP/{z}/{x}/{y}.png`,
      tilingScheme: {
        getNumberOfXTilesAtLevel: (level: number) => 1 << level,
        getNumberOfYTilesAtLevel: (level: number) => 1 << level,
      },
      requestImage: makeOkRequestImage(),
    };

    attachTileCacheToProvider(provider, { frameKey: timeKey0 });
    await provider.requestImage(0, 0, 0);
    await provider.requestImage(1, 0, 0);

    prefetchNextFrameTiles({ currentTimeKey: timeKey0, nextTimeKey: timeKey1 });
    prefetchNextFrameTiles({ currentTimeKey: timeKey1, nextTimeKey: timeKey2 });

    await vi.runAllTimersAsync();

    expect(prefetched[0]).toContain(`/${encodeURIComponent(timeKey2)}/`);
    vi.useRealTimers();
  });

  it('keeps concurrent prefetch accounting stable when cleared mid-flight', async () => {
    vi.useFakeTimers();

    const pending: Array<{ onload: (() => void) | null; onerror: (() => void) | null }> = [];
    class PendingImageStub {
      public decoding = 'async';
      public crossOrigin: string | null = null;
      public onload: (() => void) | null = null;
      public onerror: (() => void) | null = null;
      private _src = '';

      set src(value: string) {
        this._src = value;
        pending.push({ onload: this.onload, onerror: this.onerror });
      }

      get src() {
        return this._src;
      }
    }

    vi.stubGlobal('Image', PendingImageStub);
    setTilePrefetchConfig({ maxConcurrentPrefetch: 1, maxPrefetchPerFrame: 1, maxQueueSize: 10 });

    const currentTimeKey = '2024-01-15T00:00:00Z';
    const nextTimeKey = '2024-01-15T01:00:00Z';

    const provider = {
      url: `https://api.test/api/v1/tiles/cldas/${encodeURIComponent(currentTimeKey)}/TMP/{z}/{x}/{y}.png`,
      tilingScheme: {
        getNumberOfXTilesAtLevel: (level: number) => 1 << level,
        getNumberOfYTilesAtLevel: (level: number) => 1 << level,
      },
      requestImage: makeOkRequestImage(),
    };

    attachTileCacheToProvider(provider, { frameKey: currentTimeKey });
    await provider.requestImage(0, 0, 0);

    prefetchNextFrameTiles({ currentTimeKey, nextTimeKey });
    await vi.runAllTimersAsync();

    expect(pending).toHaveLength(1);

    clearTilePrefetchCache();

    await provider.requestImage(0, 0, 0);
    prefetchNextFrameTiles({ currentTimeKey, nextTimeKey });
    await vi.runAllTimersAsync();

    expect(pending).toHaveLength(1);

    clearTilePrefetchCache();
    pending.forEach((entry) => entry.onload?.());
    await vi.runAllTimersAsync();
    vi.useRealTimers();
  });

  it('prefetches next-frame tiles and serves them from cache', async () => {
    vi.useFakeTimers();

    const currentTimeKey = '2024-01-15T00:00:00Z';
    const nextTimeKey = '2024-01-15T01:00:00Z';

    const requestImageCurrent = makeOkRequestImage();
    const providerCurrent = {
      url: `https://api.test/api/v1/tiles/cldas/${encodeURIComponent(currentTimeKey)}/TMP/{z}/{x}/{y}.png`,
      tilingScheme: {
        getNumberOfXTilesAtLevel: (level: number) => 1 << level,
        getNumberOfYTilesAtLevel: (level: number) => 1 << level,
      },
      requestImage: requestImageCurrent,
    };

    attachTileCacheToProvider(providerCurrent, { frameKey: currentTimeKey });

    await providerCurrent.requestImage(0, 0, 0);

    setTilePrefetchConfig({ maxPrefetchPerFrame: 10, maxConcurrentPrefetch: 1 });
    prefetchNextFrameTiles({ currentTimeKey, nextTimeKey });

    await vi.runAllTimersAsync();

    prefetchNextFrameTiles({ currentTimeKey, nextTimeKey });

    const requestImageNext = makeOkRequestImage();
    const providerNext = {
      url: `https://api.test/api/v1/tiles/cldas/${encodeURIComponent(nextTimeKey)}/TMP/{z}/{x}/{y}.png`,
      tilingScheme: providerCurrent.tilingScheme,
      requestImage: requestImageNext,
    };

    attachTileCacheToProvider(providerNext, { frameKey: nextTimeKey });

    await providerNext.requestImage(0, 0, 0);

    expect(requestImageNext).not.toHaveBeenCalled();
    expect(getTilePrefetchStats().prefetchQueued).toBeGreaterThan(0);
    expect(getTilePrefetchStats().prefetchSuccess).toBeGreaterThan(0);

    vi.useRealTimers();
  });

  it('clears queued prefetch when the network becomes constrained', async () => {
    vi.useFakeTimers();

    const currentTimeKey = '2024-01-15T00:00:00Z';
    const nextTimeKey = '2024-01-15T01:00:00Z';

    const providerCurrent = {
      url: `https://api.test/api/v1/tiles/cldas/${encodeURIComponent(currentTimeKey)}/TMP/{z}/{x}/{y}.png`,
      tilingScheme: {
        getNumberOfXTilesAtLevel: (level: number) => 1 << level,
        getNumberOfYTilesAtLevel: (level: number) => 1 << level,
      },
      requestImage: makeOkRequestImage(),
    };

    attachTileCacheToProvider(providerCurrent, { frameKey: currentTimeKey });
    await providerCurrent.requestImage(0, 0, 0);

    prefetchNextFrameTiles({ currentTimeKey, nextTimeKey });
    prefetchNextFrameTiles({ currentTimeKey, nextTimeKey });

    setNavigatorConnection({ effectiveType: '2g', saveData: false });

    await vi.runAllTimersAsync();

    const requestImageNext = makeOkRequestImage();
    const providerNext = {
      url: `https://api.test/api/v1/tiles/cldas/${encodeURIComponent(nextTimeKey)}/TMP/{z}/{x}/{y}.png`,
      tilingScheme: providerCurrent.tilingScheme,
      requestImage: requestImageNext,
    };

    attachTileCacheToProvider(providerNext, { frameKey: nextTimeKey });
    await providerNext.requestImage(0, 0, 0);

    expect(requestImageNext).toHaveBeenCalledTimes(1);

    vi.useRealTimers();
  });

  it('enters cooldown when prefetch repeatedly fails', async () => {
    vi.useFakeTimers();

    setTilePrefetchConfig({
      consecutiveErrorCooldownThreshold: 1,
      errorCooldownMs: 60_000,
      maxConcurrentPrefetch: 1,
      maxPrefetchPerFrame: 1,
    });

    const currentTimeKey = '2024-01-15T00:00:00Z';
    const nextTimeKey = '2024-01-15T01:00:00Z';

    const providerCurrent = {
      url: `https://api.test/fail/${encodeURIComponent(currentTimeKey)}/TMP/{z}/{x}/{y}.png`,
      tilingScheme: {
        getNumberOfXTilesAtLevel: (level: number) => 1 << level,
        getNumberOfYTilesAtLevel: (level: number) => 1 << level,
      },
      requestImage: makeOkRequestImage(),
    };

    attachTileCacheToProvider(providerCurrent, { frameKey: currentTimeKey });
    await providerCurrent.requestImage(0, 0, 0);

    prefetchNextFrameTiles({ currentTimeKey, nextTimeKey });
    await vi.runAllTimersAsync();

    expect(getTilePrefetchStats().prefetchError).toBeGreaterThan(0);
    expect(getTilePrefetchDisabledReason()).toBe('cooldown');

    vi.useRealTimers();
  });
});
