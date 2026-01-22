import {
  GeographicTilingScheme,
  ImageryLayer,
  Rectangle,
  TextureMagnificationFilter,
  TextureMinificationFilter,
  UrlTemplateImageryProvider,
  type Viewer,
} from 'cesium';

import { attachTileCacheToProvider } from './tilePrefetch';
import type { RectangleDegrees } from './types';

export type AnalyticsTileLayerParams = {
  id: string;
  urlTemplate: string;
  frameKey: string;
  opacity: number;
  visible: boolean;
  zIndex: number;
  rectangle?: RectangleDegrees | null;
  minimumLevel?: number | null;
  maximumLevel?: number | null;
  credit?: string;
};

function clampOpacity(value: number): number {
  if (!Number.isFinite(value)) return 1;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

function normalizeRectangle(value: RectangleDegrees | null | undefined): Rectangle | undefined {
  if (!value) return undefined;
  const { west, south, east, north } = value;
  if (![west, south, east, north].every((item) => Number.isFinite(item))) return undefined;
  return Rectangle.fromDegrees(west, south, east, north);
}

function normalizeLevel(value: number | null | undefined): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined;
  const rounded = Math.floor(value);
  if (rounded < 0) return 0;
  return rounded;
}

function coverageKey(value: RectangleDegrees | null | undefined): string {
  if (!value) return 'global';
  const { west, south, east, north } = value;
  return `${west},${south},${east},${north}`;
}

function levelsKey(minimumLevel: number | undefined, maximumLevel: number | undefined): string {
  return `${minimumLevel ?? ''}:${maximumLevel ?? ''}`;
}

export class AnalyticsTileLayer {
  public readonly id: string;
  private readonly viewer: Viewer;
  private current: AnalyticsTileLayerParams;
  private imageryLayer: ImageryLayer | null = null;
  private urlTemplate: string | null = null;
  private frameKey: string | null = null;
  private coverageKey: string | null = null;
  private levelsKey: string | null = null;

  constructor(viewer: Viewer, params: AnalyticsTileLayerParams) {
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

  update(params: AnalyticsTileLayerParams): void {
    if (params.id !== this.id) {
      throw new Error(`AnalyticsTileLayer id mismatch: ${params.id}`);
    }

    this.current = params;
    this.sync();
  }

  destroy(): void {
    if (!this.imageryLayer) return;
    this.viewer.imageryLayers.remove(this.imageryLayer, true);
    this.imageryLayer = null;
    this.urlTemplate = null;
    this.frameKey = null;
    this.coverageKey = null;
    this.levelsKey = null;
    this.viewer.scene.requestRender();
  }

  private sync(options: { forceRecreate?: boolean } = {}): void {
    const nextTemplate = this.current.urlTemplate.trim();
    const nextFrameKey = this.current.frameKey.trim();
    const nextCoverageKey = coverageKey(this.current.rectangle);
    const minimumLevel = normalizeLevel(this.current.minimumLevel);
    const maximumLevel = normalizeLevel(this.current.maximumLevel);
    const nextLevelsKey = levelsKey(minimumLevel, maximumLevel);

    const shouldRecreate =
      options.forceRecreate ||
      this.imageryLayer === null ||
      this.urlTemplate !== nextTemplate ||
      this.frameKey !== nextFrameKey ||
      this.coverageKey !== nextCoverageKey ||
      this.levelsKey !== nextLevelsKey;

    if (shouldRecreate) {
      if (this.imageryLayer) {
        this.viewer.imageryLayers.remove(this.imageryLayer, true);
      }

      const rectangle = normalizeRectangle(this.current.rectangle);

      const provider = new UrlTemplateImageryProvider({
        url: nextTemplate,
        tilingScheme: new GeographicTilingScheme({
          numberOfLevelZeroTilesX: 1,
          numberOfLevelZeroTilesY: 1,
        }),
        ...(minimumLevel == null ? {} : { minimumLevel }),
        ...(maximumLevel == null ? {} : { maximumLevel }),
        tileWidth: 256,
        tileHeight: 256,
        rectangle,
        credit: this.current.credit ?? 'Analytics tiles',
      });
      attachTileCacheToProvider(provider, { frameKey: nextFrameKey });

      this.imageryLayer = new ImageryLayer(provider, {
        alpha: clampOpacity(this.current.opacity),
        show: this.current.visible,
      });
      this.viewer.imageryLayers.add(this.imageryLayer);
      this.imageryLayer.minificationFilter = TextureMinificationFilter.NEAREST;
      this.imageryLayer.magnificationFilter = TextureMagnificationFilter.NEAREST;
      this.urlTemplate = nextTemplate;
      this.frameKey = nextFrameKey;
      this.coverageKey = nextCoverageKey;
      this.levelsKey = nextLevelsKey;
    }

    if (!this.imageryLayer) return;

    this.imageryLayer.alpha = clampOpacity(this.current.opacity);
    this.imageryLayer.show = this.current.visible;
    this.viewer.scene.requestRender();
  }
}

