import {
  GeographicTilingScheme,
  ImageryLayer,
  TextureMagnificationFilter,
  TextureMinificationFilter,
  UrlTemplateImageryProvider,
  type Viewer,
} from 'cesium';

import { buildPrecipitationTileUrlTemplate } from './layersApi';
import { attachTileCacheToProvider } from './tilePrefetch';
import type { PrecipitationLayerParams } from './types';
import { isCesiumDestroyed, requestViewerRender } from '../../lib/cesiumSafe';

const MAX_TILE_LEVEL = 22;

function clampOpacity(value: number): number {
  if (!Number.isFinite(value)) return 1;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

function extractHttpStatusCode(value: unknown): number | null {
  if (!isRecord(value)) return null;

  const candidates = [value.statusCode, value.status, (value.error as unknown)];

  for (const candidate of candidates) {
    if (typeof candidate === 'number' && Number.isFinite(candidate)) return candidate;
    if (isRecord(candidate)) {
      const nested = candidate.statusCode ?? candidate.status;
      if (typeof nested === 'number' && Number.isFinite(nested)) return nested;
    }
  }

  return null;
}

export class PrecipitationLayer {
  public readonly id: string;
  private readonly viewer: Viewer;
  private current: PrecipitationLayerParams;
  private imageryLayer: ImageryLayer | null = null;
  private urlTemplate: string | null = null;
  private provider: UrlTemplateImageryProvider | null = null;
  private providerErrorHandler: ((error: unknown) => void) | null = null;
  private didWarnTileError = false;

  constructor(viewer: Viewer, params: PrecipitationLayerParams) {
    this.viewer = viewer;
    this.id = params.id;
    this.current = params;
    this.sync({ forceRecreate: true });
  }

  get layer(): ImageryLayer | null {
    return this.imageryLayer;
  }

  get zIndex(): number {
    return this.current.zIndex;
  }

  update(params: PrecipitationLayerParams): void {
    if (params.id !== this.id) {
      throw new Error(`PrecipitationLayer id mismatch: ${params.id}`);
    }

    this.current = params;
    this.sync();
  }

  destroy(): void {
    if (!this.imageryLayer) return;
    this.detachProviderErrorListener();
    if (!isCesiumDestroyed(this.viewer)) {
      try {
        this.viewer.imageryLayers.remove(this.imageryLayer, true);
      } catch {
        // ignore teardown errors
      }
    }
    this.imageryLayer = null;
    this.urlTemplate = null;
    requestViewerRender(this.viewer);
  }

  private detachProviderErrorListener() {
    if (!this.provider || !this.providerErrorHandler) return;
    try {
      this.provider.errorEvent.removeEventListener(this.providerErrorHandler);
    } catch {
      // ignore provider teardown errors
    }
    this.providerErrorHandler = null;
    this.provider = null;
  }

  private createUrlTemplate(params: PrecipitationLayerParams): string {
    return buildPrecipitationTileUrlTemplate({
      apiBaseUrl: params.apiBaseUrl,
      timeKey: params.timeKey,
      threshold: params.threshold,
    });
  }

  private sync(options: { forceRecreate?: boolean } = {}): void {
    if (isCesiumDestroyed(this.viewer)) return;

    const nextTemplate = this.createUrlTemplate(this.current);
    const shouldRecreate =
      options.forceRecreate ||
      this.imageryLayer === null ||
      this.urlTemplate !== nextTemplate;

    if (shouldRecreate) {
      if (this.imageryLayer) {
        this.detachProviderErrorListener();
        try {
          this.viewer.imageryLayers.remove(this.imageryLayer, true);
        } catch {
          // ignore teardown errors
        }
      }

      const provider = new UrlTemplateImageryProvider({
        url: nextTemplate,
        tilingScheme: new GeographicTilingScheme({
          numberOfLevelZeroTilesX: 1,
          numberOfLevelZeroTilesY: 1,
        }),
        maximumLevel: MAX_TILE_LEVEL,
        tileWidth: 256,
        tileHeight: 256,
        credit: 'Precipitation tiles',
      });
      attachTileCacheToProvider(provider, { frameKey: this.current.timeKey });

      this.detachProviderErrorListener();
      this.didWarnTileError = false;
      this.provider = provider;
      this.providerErrorHandler = (error: unknown) => {
        if (this.didWarnTileError) return;
        this.didWarnTileError = true;

        const statusCode = extractHttpStatusCode(error);
        const errorDetails: Record<string, unknown> = {
          statusCode,
          urlTemplate: nextTemplate,
        };

        if (isRecord(error)) {
          const tileX = error.x;
          const tileY = error.y;
          const tileLevel = error.level;
          if (typeof tileX === 'number') errorDetails.x = tileX;
          if (typeof tileY === 'number') errorDetails.y = tileY;
          if (typeof tileLevel === 'number') errorDetails.level = tileLevel;
          if (typeof error.message === 'string') errorDetails.message = error.message;
        }

        if (statusCode === 404) {
          console.warn('[Digital Earth] precipitation tiles missing (404)', errorDetails);
        } else {
          console.warn('[Digital Earth] precipitation tiles failed to load', errorDetails);
        }
      };

      try {
        provider.errorEvent.addEventListener(this.providerErrorHandler);
      } catch {
        // ignore provider event wiring errors
      }

      this.imageryLayer = new ImageryLayer(provider, {
        alpha: clampOpacity(this.current.opacity),
        show: this.current.visible,
      });
      try {
        this.viewer.imageryLayers.add(this.imageryLayer);
      } catch {
        this.detachProviderErrorListener();
        this.imageryLayer = null;
        this.urlTemplate = null;
        return;
      }
      this.imageryLayer.minificationFilter = TextureMinificationFilter.NEAREST;
      this.imageryLayer.magnificationFilter = TextureMagnificationFilter.NEAREST;
      this.urlTemplate = nextTemplate;
    }

    if (!this.imageryLayer) return;

    this.imageryLayer.alpha = clampOpacity(this.current.opacity);
    this.imageryLayer.show = this.current.visible;
    requestViewerRender(this.viewer);
  }
}
