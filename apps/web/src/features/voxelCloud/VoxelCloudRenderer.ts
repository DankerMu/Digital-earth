import {
  Cartesian2,
  Cartesian3,
  PostProcessStage,
  Math as CesiumMath,
  Transforms,
  type Viewer,
} from 'cesium';

import { decodeVolumePack, type VolumePackBBox } from '../../lib/volumePack';
import { buildAtlasCanvas, buildVolumeAtlas, type VolumeAtlas } from './atlas';
import { recommendVoxelCloudParams, type VoxelCloudRecommendedParams } from './recommendations';
import { voxelCloudRayMarchShader } from './shader';

export type VoxelCloudLoadMetrics = {
  url: string;
  bytes: number;
  fetchMs: number;
  decodeMs: number;
  atlasMs: number;
  canvasMs: number;
  totalMs: number;
  approxAtlasBytes: number;
};

export type VoxelCloudSettings = {
  enabled: boolean;
  stepVoxels: number;
  maxSteps: number;
  densityMultiplier: number;
  extinction: number;
};

export type VoxelCloudSnapshot = {
  ready: boolean;
  enabled: boolean;
  settings: VoxelCloudSettings;
  volume: {
    shape: [number, number, number];
    bbox: VolumePackBBox | null;
    dimensionsMeters: { width: number; height: number; depth: number } | null;
    atlas: Pick<
      VolumeAtlas,
      'atlasWidth' | 'atlasHeight' | 'gridCols' | 'gridRows' | 'sliceWidth' | 'sliceHeight' | 'depth'
    >;
    minValue: number;
    maxValue: number;
  } | null;
  recommended: VoxelCloudRecommendedParams | null;
  metrics: VoxelCloudLoadMetrics | null;
  lastError: string | null;
};

type PostProcessStageLike = {
  enabled: boolean;
  destroy: () => void;
};

type PostProcessStagesLike = {
  add?: (stage: unknown) => unknown;
  remove?: (stage: unknown) => void;
};

function nowMs(): number {
  return typeof performance !== 'undefined' && typeof performance.now === 'function'
    ? performance.now()
    : Date.now();
}

function isAbortError(error: unknown): boolean {
  if (!error) return false;
  if (error instanceof DOMException) return error.name === 'AbortError';
  if (error instanceof Error) return error.name === 'AbortError';
  return false;
}

function throwIfAborted(signal: AbortSignal | undefined): void {
  if (!signal?.aborted) return;
  const reason = (signal as unknown as { reason?: unknown }).reason;
  if (reason != null) throw reason;
  throw new DOMException('The operation was aborted.', 'AbortError');
}

function normalizeBBox(bbox: VolumePackBBox): VolumePackBBox {
  const west = CesiumMath.negativePiToPi(CesiumMath.toRadians(bbox.west));
  const east = CesiumMath.negativePiToPi(CesiumMath.toRadians(bbox.east));

  // If bbox crosses the dateline, keep the input as-is (PoC scope).
  return {
    west: CesiumMath.toDegrees(west),
    south: bbox.south,
    east: CesiumMath.toDegrees(east),
    north: bbox.north,
    bottom: bbox.bottom,
    top: bbox.top,
  };
}

function bboxCenterDegrees(bbox: VolumePackBBox): { lon: number; lat: number; height: number } {
  const lon = (bbox.west + bbox.east) / 2;
  const lat = (bbox.south + bbox.north) / 2;
  const height = (bbox.bottom + bbox.top) / 2;
  return { lon, lat, height };
}

function safePositive(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return null;
  return value;
}

function clamp(value: number, min: number, max: number): number {
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

export class VoxelCloudRenderer {
  private readonly viewer: Viewer;
  private stage: PostProcessStageLike | null = null;
  private atlasCanvas: HTMLCanvasElement | null = null;
  private atlasInfo: VolumeAtlas | null = null;
  private bbox: VolumePackBBox | null = null;
  private centerWorld: Cartesian3 | null = null;
  private eastWorld: Cartesian3 | null = null;
  private northWorld: Cartesian3 | null = null;
  private upWorld: Cartesian3 | null = null;
  private dimensionsMeters: { width: number; height: number; depth: number } | null = null;

  private settings: VoxelCloudSettings = {
    enabled: false,
    stepVoxels: 1,
    maxSteps: 128,
    densityMultiplier: 1.0,
    extinction: 1.2,
  };

  private recommended: VoxelCloudRecommendedParams | null = null;
  private metrics: VoxelCloudLoadMetrics | null = null;
  private lastError: string | null = null;
  private readonly atlasGridScratch = new Cartesian2(1, 1);
  private readonly volumeShapeScratch = new Cartesian3(1, 1, 1);
  private readonly dimensionsScratch = new Cartesian3(1, 1, 1);

  constructor(viewer: Viewer, options: Partial<VoxelCloudSettings> = {}) {
    this.viewer = viewer;
    this.settings = { ...this.settings, ...options };
  }

  getSnapshot(): VoxelCloudSnapshot {
    const atlasInfo = this.atlasInfo;
    return {
      ready: Boolean(this.stage && atlasInfo && this.centerWorld && this.dimensionsMeters),
      enabled: this.settings.enabled,
      settings: { ...this.settings },
      volume: atlasInfo
        ? {
            shape: [atlasInfo.depth, atlasInfo.sliceHeight, atlasInfo.sliceWidth],
            bbox: this.bbox,
            dimensionsMeters: this.dimensionsMeters,
            atlas: {
              atlasWidth: atlasInfo.atlasWidth,
              atlasHeight: atlasInfo.atlasHeight,
              gridCols: atlasInfo.gridCols,
              gridRows: atlasInfo.gridRows,
              sliceWidth: atlasInfo.sliceWidth,
              sliceHeight: atlasInfo.sliceHeight,
              depth: atlasInfo.depth,
            },
            minValue: atlasInfo.minValue,
            maxValue: atlasInfo.maxValue,
          }
        : null,
      recommended: this.recommended,
      metrics: this.metrics,
      lastError: this.lastError,
    };
  }

  setEnabled(enabled: boolean): void {
    this.settings.enabled = Boolean(enabled);
    if (this.stage) {
      this.stage.enabled = this.settings.enabled;
    }
    this.viewer.scene.requestRender();
  }

  updateSettings(partial: Partial<Omit<VoxelCloudSettings, 'enabled'>>): void {
    this.settings = { ...this.settings, ...partial };
    this.viewer.scene.requestRender();
  }

  async loadFromUrl(url: string, options: { signal?: AbortSignal } = {}): Promise<void> {
    const startedAt = nowMs();
    this.lastError = null;
    const signal = options.signal;

    try {
      throwIfAborted(signal);

      const fetchStartedAt = nowMs();
      const response = await fetch(url, { signal });
      if (!response.ok) {
        throw new Error(`Failed to fetch volume pack (${response.status})`);
      }
      const bytes = await response.arrayBuffer();
      const fetchMs = nowMs() - fetchStartedAt;

      throwIfAborted(signal);

      const decodeStartedAt = nowMs();
      const decoded = decodeVolumePack(bytes);
      const decodeMs = nowMs() - decodeStartedAt;

      throwIfAborted(signal);

      const bbox = decoded.header.bbox ? normalizeBBox(decoded.header.bbox as VolumePackBBox) : null;
      this.bbox = bbox;

      if (!bbox) {
        throw new Error('Volume Pack header.bbox is required for voxel cloud PoC');
      }

      const dims = this.computeVolumeDimensionsMeters(bbox);
      this.dimensionsMeters = dims;

      const { lon, lat, height } = bboxCenterDegrees(bbox);
      const centerWorld = Cartesian3.fromDegrees(lon, lat, height);
      this.centerWorld = centerWorld;

      throwIfAborted(signal);

      const frame = Transforms.eastNorthUpToFixedFrame(centerWorld);
      this.eastWorld = new Cartesian3(frame[0], frame[1], frame[2]);
      this.northWorld = new Cartesian3(frame[4], frame[5], frame[6]);
      this.upWorld = new Cartesian3(frame[8], frame[9], frame[10]);

      throwIfAborted(signal);

      const atlasStartedAt = nowMs();
      const atlas = buildVolumeAtlas(decoded);
      this.atlasInfo = atlas;
      const atlasMs = nowMs() - atlasStartedAt;

      throwIfAborted(signal);

      const canvasStartedAt = nowMs();
      const { canvas, approxBytes } = buildAtlasCanvas(atlas.atlas, atlas.atlasWidth, atlas.atlasHeight);
      this.atlasCanvas = canvas;
      const canvasMs = nowMs() - canvasStartedAt;

      throwIfAborted(signal);

      this.recommended = recommendVoxelCloudParams({
        volumeShape: decoded.shape,
        dimensionsMeters: dims,
        targetMaxSteps: this.settings.maxSteps,
      });

      if (this.recommended.stepMeters != null) {
        this.settings.stepVoxels = this.recommended.stepVoxels;
      }

      this.ensureStage();
      this.setEnabled(this.settings.enabled);

      const totalMs = nowMs() - startedAt;

      this.metrics = {
        url,
        bytes: bytes.byteLength,
        fetchMs,
        decodeMs,
        atlasMs,
        canvasMs,
        totalMs,
        approxAtlasBytes: approxBytes,
      };

      this.viewer.scene.requestRender();
    } catch (error) {
      if (signal?.aborted || isAbortError(error)) {
        throw error;
      }
      this.lastError = error instanceof Error ? error.message : String(error);
      throw error;
    }
  }

  destroy(): void {
    const stages = (this.viewer.scene as unknown as { postProcessStages?: PostProcessStagesLike })
      .postProcessStages;
    if (stages?.remove && this.stage) {
      stages.remove(this.stage);
    }
    this.stage?.destroy();
    this.stage = null;
    this.atlasCanvas = null;
    this.atlasInfo = null;
    this.bbox = null;
    this.centerWorld = null;
    this.eastWorld = null;
    this.northWorld = null;
    this.upWorld = null;
    this.dimensionsMeters = null;
    this.viewer.scene.requestRender();
  }

  private computeVolumeDimensionsMeters(bbox: VolumePackBBox): { width: number; height: number; depth: number } {
    const center = bboxCenterDegrees(bbox);

    const midHeight = center.height;
    const midLat = center.lat;
    const midLon = center.lon;

    const westPoint = Cartesian3.fromDegrees(bbox.west, midLat, midHeight);
    const eastPoint = Cartesian3.fromDegrees(bbox.east, midLat, midHeight);
    const southPoint = Cartesian3.fromDegrees(midLon, bbox.south, midHeight);
    const northPoint = Cartesian3.fromDegrees(midLon, bbox.north, midHeight);
    const bottomPoint = Cartesian3.fromDegrees(midLon, midLat, bbox.bottom);
    const topPoint = Cartesian3.fromDegrees(midLon, midLat, bbox.top);

    const width = Cartesian3.distance(westPoint, eastPoint);
    const height = Cartesian3.distance(southPoint, northPoint);
    const depth = Cartesian3.distance(bottomPoint, topPoint);

    const normalizedWidth = safePositive(width) ?? 1;
    const normalizedHeight = safePositive(height) ?? 1;
    const normalizedDepth = safePositive(depth) ?? 1;

    return { width: normalizedWidth, height: normalizedHeight, depth: normalizedDepth };
  }

  private ensureStage(): void {
    if (this.stage) return;

    const stages = (this.viewer.scene as unknown as { postProcessStages?: PostProcessStagesLike })
      .postProcessStages;
    if (!stages?.add) {
      throw new Error('Cesium viewer.scene.postProcessStages is not available');
    }

    const uniforms = {
      u_volumeAtlas: () => this.atlasCanvas,
      u_atlasGrid: () => {
        if (!this.atlasInfo) return this.atlasGridScratch;
        this.atlasGridScratch.x = this.atlasInfo.gridCols;
        this.atlasGridScratch.y = this.atlasInfo.gridRows;
        return this.atlasGridScratch;
      },
      u_volumeShape: () => {
        if (!this.atlasInfo) return this.volumeShapeScratch;
        this.volumeShapeScratch.x = this.atlasInfo.sliceWidth;
        this.volumeShapeScratch.y = this.atlasInfo.sliceHeight;
        this.volumeShapeScratch.z = this.atlasInfo.depth;
        return this.volumeShapeScratch;
      },
      u_centerWorld: () => this.centerWorld ?? Cartesian3.ZERO,
      u_eastWorld: () => this.eastWorld ?? Cartesian3.UNIT_X,
      u_northWorld: () => this.northWorld ?? Cartesian3.UNIT_Y,
      u_upWorld: () => this.upWorld ?? Cartesian3.UNIT_Z,
      u_dimensionsMeters: () => {
        const dims = this.dimensionsMeters;
        if (!dims) return this.dimensionsScratch;
        this.dimensionsScratch.x = dims.width;
        this.dimensionsScratch.y = dims.height;
        this.dimensionsScratch.z = dims.depth;
        return this.dimensionsScratch;
      },
      u_stepMeters: () => {
        const atlasInfo = this.atlasInfo;
        const dims = this.dimensionsMeters;
        if (!atlasInfo || !dims) return 1.0;

        const voxelSizeX = dims.width / atlasInfo.sliceWidth;
        const voxelSizeY = dims.height / atlasInfo.sliceHeight;
        const voxelSizeZ = dims.depth / atlasInfo.depth;
        const base = Math.min(voxelSizeX, voxelSizeY, voxelSizeZ);
        const step = base * this.settings.stepVoxels;
        return clamp(step, 0.1, 10_000);
      },
      u_maxSteps: () => Math.round(clamp(this.settings.maxSteps, 1, 512)),
      u_densityMultiplier: () => clamp(this.settings.densityMultiplier, 0, 10),
      u_extinction: () => clamp(this.settings.extinction, 0, 10),
    };

    const stage = new PostProcessStage({
      name: 'VoxelCloudRayMarch',
      fragmentShader: voxelCloudRayMarchShader,
      uniforms,
    }) as unknown as PostProcessStageLike;
    this.stage = stage;
    stages.add(stage);
  }
}
