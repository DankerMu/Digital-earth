import {
  GeographicTilingScheme,
  ImageryLayer,
  TextureMagnificationFilter,
  TextureMinificationFilter,
  UrlTemplateImageryProvider,
  type Viewer,
} from 'cesium';

import { buildEcmwfTemperatureTileUrlTemplate } from './layersApi';
import { attachTileCacheToProvider } from './tilePrefetch';
import type { TemperatureLayerParams } from './types';

const MAX_TILE_LEVEL = 22;

function clampOpacity(value: number): number {
  if (!Number.isFinite(value)) return 1;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

export class TemperatureLayer {
  public readonly id: string;
  private readonly viewer: Viewer;
  private current: TemperatureLayerParams;
  private imageryLayer: ImageryLayer | null = null;
  private urlTemplate: string | null = null;

  constructor(viewer: Viewer, params: TemperatureLayerParams) {
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

  update(params: TemperatureLayerParams): void {
    if (params.id !== this.id) {
      throw new Error(`TemperatureLayer id mismatch: ${params.id}`);
    }

    this.current = params;
    this.sync();
  }

  destroy(): void {
    if (!this.imageryLayer) return;
    this.viewer.imageryLayers.remove(this.imageryLayer, true);
    this.imageryLayer = null;
    this.urlTemplate = null;
    this.viewer.scene.requestRender();
  }

  private createUrlTemplate(params: TemperatureLayerParams): string {
    return buildEcmwfTemperatureTileUrlTemplate({
      apiBaseUrl: params.apiBaseUrl,
      timeKey: params.timeKey,
      level: params.levelKey ?? 'sfc',
    });
  }

  private sync(options: { forceRecreate?: boolean } = {}): void {
    const nextTemplate = this.createUrlTemplate(this.current);
    const shouldRecreate =
      options.forceRecreate ||
      this.imageryLayer === null ||
      this.urlTemplate !== nextTemplate;

    if (shouldRecreate) {
      if (this.imageryLayer) {
        this.viewer.imageryLayers.remove(this.imageryLayer, true);
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
        credit: 'Temperature tiles',
      });
      attachTileCacheToProvider(provider, { frameKey: this.current.timeKey });

      this.imageryLayer = new ImageryLayer(provider, {
        alpha: clampOpacity(this.current.opacity),
        show: this.current.visible,
      });
      this.viewer.imageryLayers.add(this.imageryLayer);
      this.imageryLayer.minificationFilter = TextureMinificationFilter.NEAREST;
      this.imageryLayer.magnificationFilter = TextureMagnificationFilter.NEAREST;
      this.urlTemplate = nextTemplate;
    }

    if (!this.imageryLayer) return;

    this.imageryLayer.alpha = clampOpacity(this.current.opacity);
    this.imageryLayer.show = this.current.visible;
    this.viewer.scene.requestRender();
  }
}
