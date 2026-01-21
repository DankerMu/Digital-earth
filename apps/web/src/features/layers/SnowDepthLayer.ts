import {
  GeographicTilingScheme,
  ImageryLayer,
  Rectangle,
  TextureMagnificationFilter,
  TextureMinificationFilter,
  UrlTemplateImageryProvider,
  type Viewer,
} from 'cesium';

import { alignToMostRecentHourTimeKey, normalizeSnowDepthVariable } from './cldasTime';
import { buildCldasTileUrlTemplate } from './layersApi';
import type { SnowDepthLayerParams } from './types';

const MAX_TILE_LEVEL = 22;

function clampOpacity(value: number): number {
  if (!Number.isFinite(value)) return 1;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

function normalizeRectangle(value: SnowDepthLayerParams['rectangle']): Rectangle | undefined {
  if (!value) return undefined;
  const { west, south, east, north } = value;
  if (![west, south, east, north].every((item) => Number.isFinite(item))) return undefined;
  return Rectangle.fromDegrees(west, south, east, north);
}

export class SnowDepthLayer {
  public readonly id: string;
  private readonly viewer: Viewer;
  private current: SnowDepthLayerParams;
  private imageryLayer: ImageryLayer | null = null;
  private urlTemplate: string | null = null;
  private coverageKey: string | null = null;

  constructor(viewer: Viewer, params: SnowDepthLayerParams) {
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

  update(params: SnowDepthLayerParams): void {
    if (params.id !== this.id) {
      throw new Error(`SnowDepthLayer id mismatch: ${params.id}`);
    }

    this.current = params;
    this.sync();
  }

  destroy(): void {
    if (!this.imageryLayer) return;
    this.viewer.imageryLayers.remove(this.imageryLayer, true);
    this.imageryLayer = null;
    this.urlTemplate = null;
    this.coverageKey = null;
    this.viewer.scene.requestRender();
  }

  private createUrlTemplate(params: SnowDepthLayerParams): string {
    const timeKey = alignToMostRecentHourTimeKey(params.timeKey);
    return buildCldasTileUrlTemplate({
      apiBaseUrl: params.apiBaseUrl,
      timeKey,
      variable: normalizeSnowDepthVariable(params.variable),
    });
  }

  private nextCoverageKey(params: SnowDepthLayerParams): string {
    const rect = params.rectangle;
    if (!rect) return 'global';
    const { west, south, east, north } = rect;
    return `${west},${south},${east},${north}`;
  }

  private sync(options: { forceRecreate?: boolean } = {}): void {
    const nextTemplate = this.createUrlTemplate(this.current);
    const nextCoverage = this.nextCoverageKey(this.current);
    const shouldRecreate =
      options.forceRecreate ||
      this.imageryLayer === null ||
      this.urlTemplate !== nextTemplate ||
      this.coverageKey !== nextCoverage;

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
        rectangle: normalizeRectangle(this.current.rectangle),
        credit: 'Snow depth tiles',
      });

      this.imageryLayer = new ImageryLayer(provider, {
        alpha: clampOpacity(this.current.opacity),
        show: this.current.visible,
      });
      this.viewer.imageryLayers.add(this.imageryLayer);
      this.imageryLayer.minificationFilter = TextureMinificationFilter.NEAREST;
      this.imageryLayer.magnificationFilter = TextureMagnificationFilter.NEAREST;
      this.urlTemplate = nextTemplate;
      this.coverageKey = nextCoverage;
    }

    if (!this.imageryLayer) return;

    this.imageryLayer.alpha = clampOpacity(this.current.opacity);
    this.imageryLayer.show = this.current.visible;
    this.viewer.scene.requestRender();
  }
}

