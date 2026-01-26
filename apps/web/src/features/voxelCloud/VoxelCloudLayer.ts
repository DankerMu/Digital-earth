import type { Camera, Viewer } from 'cesium';

import { requestViewerRender } from '../../lib/cesiumSafe';

import { computeLocalModeBBox } from './bboxCalculator';
import { VoxelCloudPerformanceMonitor } from './performanceMonitor';
import { QUALITY_PRESETS, type VoxelCloudQuality } from './qualityConfig';
import { fetchVolumePack } from './volumeApi';
import { VolumeCache } from './volumeCache';
import { VoxelCloudRenderer } from './VoxelCloudRenderer';

function nowMs(): number {
  return typeof performance !== 'undefined' && typeof performance.now === 'function'
    ? performance.now()
    : Date.now();
}

function isAbortError(error: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) return true;
  if (error instanceof DOMException) return error.name === 'AbortError';
  if (error instanceof Error) return error.name === 'AbortError';
  return false;
}

function downgradeQuality(quality: VoxelCloudQuality): VoxelCloudQuality {
  if (quality === 'high') return 'medium';
  if (quality === 'medium') return 'low';
  return 'low';
}

function upgradeQuality(quality: VoxelCloudQuality): VoxelCloudQuality {
  if (quality === 'low') return 'medium';
  if (quality === 'medium') return 'high';
  return 'high';
}

export type VoxelCloudLayerOptions = {
  apiBaseUrl: string;
  levels: number[];
  quality?: VoxelCloudQuality;
  autoDowngrade?: boolean;
  validTime?: string | null;
  cacheEntries?: number;
};

export class VoxelCloudLayer {
  private readonly viewer: Viewer;
  public readonly renderer: VoxelCloudRenderer;
  private readonly cache: VolumeCache;
  private readonly options: VoxelCloudLayerOptions;

  private qualityValue: VoxelCloudQuality;
  private autoDowngradeValue: boolean;
  private performanceMonitor = new VoxelCloudPerformanceMonitor();
  private lastApiCallAtMs = -Infinity;
  private lastFrameAtMs: number | null = null;
  private detachPostRender: (() => void) | null = null;

  private loadAbortController: AbortController | null = null;
  private inFlightKey: string | null = null;
  private lastLoadedKey: string | null = null;
  private requestToken = 0;
  private fallbackActive = false;

  constructor(viewer: Viewer, options: VoxelCloudLayerOptions) {
    this.viewer = viewer;
    this.options = options;
    this.cache = new VolumeCache(options.cacheEntries ?? 4);
    this.qualityValue = options.quality ?? 'high';
    this.autoDowngradeValue = options.autoDowngrade ?? false;
    this.renderer = new VoxelCloudRenderer(viewer, { enabled: true });
    this.applyQualityPreset();
    this.renderer.setEnabled(true);
    this.attachPostRenderMonitor();
  }

  destroy(): void {
    this.loadAbortController?.abort();
    this.loadAbortController = null;
    this.inFlightKey = null;
    this.lastLoadedKey = null;
    this.detachPostRender?.();
    this.detachPostRender = null;
    this.renderer.destroy();
  }

  get quality(): VoxelCloudQuality {
    return this.qualityValue;
  }

  set quality(quality: VoxelCloudQuality) {
    this.setQuality(quality);
  }

  get autoDowngrade(): boolean {
    return this.autoDowngradeValue;
  }

  set autoDowngrade(enabled: boolean) {
    this.setAutoDowngrade(enabled);
  }

  setQuality(quality: VoxelCloudQuality): void {
    if (this.qualityValue === quality) return;
    this.qualityValue = quality;
    this.applyQualityPreset();
    this.lastApiCallAtMs = -Infinity;
    this.lastLoadedKey = null;
    this.cancelInFlight();
    requestViewerRender(this.viewer);
  }

  setAutoDowngrade(enabled: boolean): void {
    this.autoDowngradeValue = Boolean(enabled);
    if (!this.autoDowngradeValue) {
      this.performanceMonitor = new VoxelCloudPerformanceMonitor();
    }
  }

  recordFrame(deltaMs: number): void {
    this.performanceMonitor.recordFrame(deltaMs);
    if (!this.autoDowngradeValue) return;

    if (this.performanceMonitor.shouldDowngrade()) {
      const next = downgradeQuality(this.qualityValue);
      if (next !== this.qualityValue) {
        this.performanceMonitor = new VoxelCloudPerformanceMonitor();
        this.setQuality(next);
      }
      return;
    }

    if (this.performanceMonitor.shouldUpgrade()) {
      const next = upgradeQuality(this.qualityValue);
      if (next !== this.qualityValue) {
        this.performanceMonitor = new VoxelCloudPerformanceMonitor();
        this.setQuality(next);
      }
    }
  }

  async updateForCamera(camera: Camera): Promise<void> {
    const apiBaseUrl = this.options.apiBaseUrl.trim();
    if (!apiBaseUrl) {
      this.activateFallback();
      return;
    }

    const preset = QUALITY_PRESETS[this.qualityValue];
    const bbox = computeLocalModeBBox(camera);
    const cacheKey = VolumeCache.makeCacheKey(
      bbox,
      this.options.levels,
      preset.res,
      this.options.validTime ?? undefined,
    );

    const cached = this.cache.get(cacheKey);
    if (cached) {
      if (this.lastLoadedKey === cacheKey) {
        if (this.inFlightKey && this.inFlightKey !== cacheKey) {
          this.loadAbortController?.abort();
          this.loadAbortController = null;
          this.inFlightKey = null;
          this.requestToken += 1;
          requestViewerRender(this.viewer);
        }
        return;
      }

      if (this.inFlightKey === cacheKey) return;

      this.loadAbortController?.abort();
      const controller = new AbortController();
      this.loadAbortController = controller;
      this.inFlightKey = cacheKey;
      const token = (this.requestToken += 1);

      try {
        await this.renderer.loadFromArrayBuffer(cached, { signal: controller.signal });
        if (controller.signal.aborted || token !== this.requestToken) return;
        this.renderer.setEnabled(true);
        this.fallbackActive = false;
        this.lastLoadedKey = cacheKey;
      } catch (error) {
        if (isAbortError(error, controller.signal)) return;
        console.warn('[Digital Earth] cached voxel volume failed, using 2D cloud layer fallback', error);
        this.activateFallback();
      } finally {
        if (this.loadAbortController === controller) this.loadAbortController = null;
        if (this.inFlightKey === cacheKey) this.inFlightKey = null;
        requestViewerRender(this.viewer);
      }
      return;
    }

    if (this.inFlightKey === cacheKey) return;

    const now = nowMs();
    if (now - this.lastApiCallAtMs < preset.updateInterval) {
      if (this.inFlightKey && this.inFlightKey !== cacheKey) {
        this.cancelInFlight();
        requestViewerRender(this.viewer);
      }
      return;
    }

    this.lastApiCallAtMs = now;
    this.loadAbortController?.abort();
    const controller = new AbortController();
    this.loadAbortController = controller;
    this.inFlightKey = cacheKey;
    const token = (this.requestToken += 1);

    try {
      const data = await fetchVolumePack(
        {
          apiBaseUrl,
          bbox,
          levels: this.options.levels,
          res: preset.res,
          ...(this.options.validTime ? { validTime: this.options.validTime } : {}),
        },
        { signal: controller.signal },
      );

      if (controller.signal.aborted || token !== this.requestToken) return;

      this.cache.set(cacheKey, data);
      await this.renderer.loadFromArrayBuffer(data, { signal: controller.signal });

      if (controller.signal.aborted || token !== this.requestToken) return;

      this.renderer.setEnabled(true);
      this.fallbackActive = false;
      this.lastLoadedKey = cacheKey;
    } catch (error) {
      if (isAbortError(error, controller.signal)) return;
      console.warn('[Digital Earth] Volume API failed, using 2D cloud layer fallback', error);
      this.activateFallback();
    } finally {
      if (this.loadAbortController === controller) this.loadAbortController = null;
      if (this.inFlightKey === cacheKey) this.inFlightKey = null;
      requestViewerRender(this.viewer);
    }
  }

  private cancelInFlight(): void {
    this.loadAbortController?.abort();
    this.loadAbortController = null;
    this.inFlightKey = null;
    this.requestToken += 1;
  }

  private applyQualityPreset(): void {
    const preset = QUALITY_PRESETS[this.qualityValue];
    this.renderer.setRaySteps(preset.raySteps);
  }

  private attachPostRenderMonitor(): void {
    const scene = this.viewer.scene as unknown as {
      postRender?: { addEventListener?: (listener: () => void) => void; removeEventListener?: (listener: () => void) => void };
    };
    const postRender = scene.postRender;
    if (!postRender?.addEventListener || !postRender.removeEventListener) return;

    const onPostRender = () => {
      const now = nowMs();
      const last = this.lastFrameAtMs;
      this.lastFrameAtMs = now;
      if (last == null) return;
      this.recordFrame(now - last);
    };

    postRender.addEventListener(onPostRender);
    this.detachPostRender = () => {
      postRender.removeEventListener?.(onPostRender);
    };
  }

  private activateFallback(): void {
    if (this.fallbackActive) return;
    this.fallbackActive = true;
    this.lastLoadedKey = null;
    this.cancelInFlight();
    this.renderer.setEnabled(false);
    requestViewerRender(this.viewer);
  }
}
