import type { Camera, Viewer } from 'cesium';

import { computeLocalModeBBox } from './bboxCalculator';
import { fetchVolumePack } from './volumeApi';
import { VolumeCache } from './volumeCache';
import { VoxelCloudRenderer } from './VoxelCloudRenderer';

function isAbortError(error: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) return true;
  if (error instanceof DOMException) return error.name === 'AbortError';
  if (error instanceof Error) return error.name === 'AbortError';
  return false;
}

export type VoxelCloudLayerOptions = {
  apiBaseUrl: string;
  levels: number[];
  res: number;
  validTime?: string | null;
  cacheEntries?: number;
};

export class VoxelCloudLayer {
  private readonly viewer: Viewer;
  public readonly renderer: VoxelCloudRenderer;
  private readonly cache: VolumeCache;
  private readonly options: VoxelCloudLayerOptions;

  private loadAbortController: AbortController | null = null;
  private inFlightKey: string | null = null;
  private requestToken = 0;
  private fallbackActive = false;

  constructor(viewer: Viewer, options: VoxelCloudLayerOptions) {
    this.viewer = viewer;
    this.options = options;
    this.cache = new VolumeCache(options.cacheEntries ?? 4);
    this.renderer = new VoxelCloudRenderer(viewer, { enabled: true });
    this.renderer.setEnabled(true);
  }

  destroy(): void {
    this.loadAbortController?.abort();
    this.loadAbortController = null;
    this.inFlightKey = null;
    this.renderer.destroy();
  }

  async updateForCamera(camera: Camera): Promise<void> {
    const apiBaseUrl = this.options.apiBaseUrl.trim();
    if (!apiBaseUrl) {
      this.activateFallback();
      return;
    }

    const bbox = computeLocalModeBBox(camera);
    const cacheKey = VolumeCache.makeCacheKey(
      bbox,
      this.options.levels,
      this.options.res,
      this.options.validTime ?? undefined,
    );

    const cached = this.cache.get(cacheKey);
    if (cached) {
      this.loadAbortController?.abort();
      this.loadAbortController = null;
      this.inFlightKey = null;
      this.requestToken += 1;

      try {
        await this.renderer.loadFromArrayBuffer(cached);
        this.renderer.setEnabled(true);
        this.fallbackActive = false;
      } catch (error) {
        if (isAbortError(error)) return;
        console.warn('[Digital Earth] cached voxel volume failed, using 2D cloud layer fallback', error);
        this.activateFallback();
      } finally {
        this.viewer.scene.requestRender();
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
      const data = await fetchVolumePack(
        {
          apiBaseUrl,
          bbox,
          levels: this.options.levels,
          res: this.options.res,
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
    } catch (error) {
      if (isAbortError(error, controller.signal)) return;
      console.warn('[Digital Earth] Volume API failed, using 2D cloud layer fallback', error);
      this.activateFallback();
    } finally {
      if (this.loadAbortController === controller) this.loadAbortController = null;
      if (this.inFlightKey === cacheKey) this.inFlightKey = null;
      this.viewer.scene.requestRender();
    }
  }

  private activateFallback(): void {
    if (this.fallbackActive) return;
    this.fallbackActive = true;
    this.loadAbortController?.abort();
    this.loadAbortController = null;
    this.inFlightKey = null;
    this.renderer.setEnabled(false);
    this.viewer.scene.requestRender();
  }
}
