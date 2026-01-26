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

export class PrecipitationLayer {
  public readonly id: string;
  private readonly viewer: Viewer;
  private current: PrecipitationLayerParams;
  private imageryLayer: ImageryLayer | null = null;
  private urlTemplate: string | null = null;

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

      this.imageryLayer = new ImageryLayer(provider, {
        alpha: clampOpacity(this.current.opacity),
        show: this.current.visible,
      });
      try {
        this.viewer.imageryLayers.add(this.imageryLayer);
      } catch {
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
