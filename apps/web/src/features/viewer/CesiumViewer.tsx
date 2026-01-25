import {
  CameraEventType,
  Cartographic,
  Cartesian3,
  CustomDataSource,
  CesiumTerrainProvider,
  Color,
  createOsmBuildingsAsync,
  createWorldImageryAsync,
  createWorldTerrainAsync,
  Ellipsoid,
  EllipsoidTerrainProvider,
  Entity,
  ImageryLayer,
  Ion,
  KeyboardEventModifier,
  Math as CesiumMath,
  PolygonGraphics,
  PolygonHierarchy,
  Rectangle,
  SceneMode,
  SceneTransforms,
  ScreenSpaceEventType,
  sampleTerrainMostDetailed,
  UrlTemplateImageryProvider,
  Viewer,
  WebMercatorTilingScheme,
  type Cesium3DTileset,
  type PrimitiveCollection,
  type Scene,
  type Viewer as CesiumViewerInstance
} from 'cesium';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { loadConfig, type MapConfig } from '../../config';
import { DEFAULT_BASEMAP_ID, getBasemapById, type BasemapId } from '../../config/basemaps';
import { useBasemapStore } from '../../state/basemap';
import { useCameraPerspectiveStore, type CameraPerspectiveId } from '../../state/cameraPerspective';
import {
  canonicalizeEventType,
  resolveEventLayerTemplateSpec,
  useEventAutoLayersStore,
} from '../../state/eventAutoLayers';
import { useEventLayersStore } from '../../state/eventLayers';
import { useLayerManagerStore, type LayerConfig, type LayerType } from '../../state/layerManager';
import { useLayoutPanelsStore } from '../../state/layoutPanels';
import { useOsmBuildingsStore } from '../../state/osmBuildings';
import { usePerformanceModeStore } from '../../state/performanceMode';
import { useSceneModeStore } from '../../state/sceneMode';
import { useTimeStore } from '../../state/time';
import { useViewerStatsStore } from '../../state/viewerStats';
import { useViewModeStore, type ViewModeRoute } from '../../state/viewMode';
import { AircraftDemoLayer } from '../aircraft/AircraftDemoLayer';
import { PrecipitationParticles } from '../effects/PrecipitationParticles';
import { DisasterDemo } from '../effects/DisasterDemo';
import { WindArrows, windArrowDensityForCameraHeight } from '../effects/WindArrows';
import { createCloudSampler, createWeatherSampler } from '../effects/weatherSampler';
import { fetchBiasTileSets, fetchHistoricalStatistics } from '../analytics/analyticsApi';
import { AnalyticsTileLayer, type AnalyticsTileLayerParams } from '../layers/AnalyticsTileLayer';
import { CloudLayer } from '../layers/CloudLayer';
import { LocalCloudStack } from '../layers/LocalCloudStack';
import { PrecipitationLayer } from '../layers/PrecipitationLayer';
import { SnowDepthLayer } from '../layers/SnowDepthLayer';
import { TemperatureLayer } from '../layers/TemperatureLayer';
import { alignToMostRecentHourTimeKey, normalizeSnowDepthVariable } from '../layers/cldasTime';
import {
  buildEcmwfTemperatureTileUrlTemplate,
  buildCloudTileUrlTemplate,
  buildPrecipitationTileUrlTemplate,
  probeCldasTileAvailability,
  fetchWindVectorData,
  type WindVector,
} from '../layers/layersApi';
import { LocalInfoPanel } from '../local/LocalInfoPanel';
import { SamplingCard } from '../sampling/SamplingCard';
import { useSamplingCard } from '../sampling/useSamplingCard';
import { CompassControl } from './CompassControl';
import { EventLayersToggle, type EventLayerModeStatus } from './EventLayersToggle';
import { createFpsMonitor, createLowFpsDetector } from './fpsMonitor';
import {
  createImageryProviderForBasemap,
  createImageryProviderForBasemapAsync,
  normalizeTmsTemplate,
  setViewerImageryProvider,
} from './cesiumBasemap';
import { switchViewerSceneMode } from './cesiumSceneMode';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import { getProductDetail } from '../products/productsApi';
import type { BBox, ProductHazardDetail } from '../products/productsTypes';
import { evaluateRisk, getRiskPois } from '../risk/riskApi';
import { formatRiskLevel, riskSeverityForLevel, type POIRiskResult, type RiskPOI } from '../risk/riskTypes';
import { RiskPoiPopup } from '../risk/RiskPoiPopup';
import { extractGeoJsonPolygons, type LonLat } from './geoJsonPolygons';

const DEFAULT_CAMERA = {
  longitude: 116.391,
  latitude: 39.9075,
  heightMeters: 20_000_000
} as const;

const MIN_ZOOM_DISTANCE_METERS = 100;
const MAX_ZOOM_DISTANCE_METERS = 40_000_000;

const CLOUD_LAYER_REFRESH_INTERVAL_MS = 5 * 60 * 1000;
const CLOUD_LAYER_FRAME_COUNT = 24;
const CLOUD_LAYER_FRAME_STEP_MS = 60 * 60 * 1000;
const WEATHER_SAMPLE_THROTTLE_MS = 750;
const WEATHER_SAMPLE_ZOOM = 8;
const WIND_VECTOR_THROTTLE_MS = 800;
const WIND_ARROWS_MAX_COUNT = 500;
const WIND_VECTOR_CACHE_MAX_ENTRIES = 20;
const EVENT_ANALYTICS_LIST_LIMIT = 25;

const LOCAL_FREE_PITCH = -Math.PI / 4;
const LOCAL_FORWARD_PITCH = 0;
const LOCAL_UPWARD_PITCH = CesiumMath.PI_OVER_TWO - Math.PI / 12;
const HUMAN_EYE_HEIGHT_METERS = 1.7;
const HUMAN_SAFE_HEIGHT_OFFSET_METERS = 350;
const HUMAN_MIN_ZOOM_DISTANCE_METERS = 1;

const LAYER_GLOBAL_SHELL_HEIGHT_METERS_BY_LAYER_TYPE: Record<LayerType, number> = {
  temperature: 2000,
  cloud: 5000,
  precipitation: 3000,
  wind: 8000,
  'snow-depth': 2500,
};

type LongitudeInterval = { start: number; end: number };

function normalizeLongitude360(value: number): number {
  const normalized = ((value % 360) + 360) % 360;
  return normalized === 360 ? 0 : normalized;
}

function normalizeLongitude180(value: number): number {
  const normalized = normalizeLongitude360(value);
  if (normalized > 180) return normalized - 360;
  return normalized;
}

function mergeLongitudeIntervals(intervals: LongitudeInterval[]): LongitudeInterval[] {
  if (intervals.length === 0) return [];
  const sorted = [...intervals].sort((a, b) => a.start - b.start);
  const merged: LongitudeInterval[] = [];

  for (const interval of sorted) {
    const last = merged[merged.length - 1];
    if (!last || interval.start > last.end) {
      merged.push({ start: interval.start, end: interval.end });
      continue;
    }
    last.end = Math.max(last.end, interval.end);
  }

  return merged;
}

function longitudeRangeUnion(bboxes: BBox[]): { west: number; east: number } {
  const intervals: LongitudeInterval[] = [];

  for (const bbox of bboxes) {
    const start = normalizeLongitude360(bbox.min_x);
    const end = normalizeLongitude360(bbox.max_x);
    if (start <= end) {
      intervals.push({ start, end });
      continue;
    }
    intervals.push({ start, end: 360 });
    intervals.push({ start: 0, end });
  }

  const merged = mergeLongitudeIntervals(intervals);
  if (merged.length === 0) {
    return { west: bboxes[0]?.min_x ?? 0, east: bboxes[0]?.max_x ?? 0 };
  }

  const covered = merged.reduce((sum, interval) => sum + (interval.end - interval.start), 0);
  if (covered >= 360) {
    return { west: -180, east: 180 };
  }

  let maxGap = -1;
  let maxGapIndex = 0;
  for (let index = 0; index < merged.length; index += 1) {
    const current = merged[index]!;
    const next = merged[(index + 1) % merged.length]!;
    const gap = index === merged.length - 1 ? next.start + 360 - current.end : next.start - current.end;
    if (gap > maxGap) {
      maxGap = gap;
      maxGapIndex = index;
    }
  }

  const start = merged[(maxGapIndex + 1) % merged.length]!.start;
  const end = merged[maxGapIndex]!.end;
  const west = normalizeLongitude180(start);
  const east = normalizeLongitude180(end === 360 ? 0 : end);
  return { west, east };
}

function bboxUnion(bboxes: BBox[]): BBox | null {
  if (bboxes.length === 0) return null;
  let min_y = bboxes[0]!.min_y;
  let max_y = bboxes[0]!.max_y;

  for (const bbox of bboxes.slice(1)) {
    min_y = Math.min(min_y, bbox.min_y);
    max_y = Math.max(max_y, bbox.max_y);
  }

  const { west, east } = longitudeRangeUnion(bboxes);
  return { min_x: west, min_y, max_x: east, max_y };
}

function materialForSeverity(severity: string): { fill: Color; outline: Color } {
  const normalized = severity.trim().toLowerCase();
  if (normalized === 'high') return { fill: Color.RED.withAlpha(0.35), outline: Color.RED };
  if (normalized === 'medium') return { fill: Color.ORANGE.withAlpha(0.35), outline: Color.ORANGE };
  if (normalized === 'low') return { fill: Color.YELLOW.withAlpha(0.35), outline: Color.YELLOW };
  return { fill: Color.CYAN.withAlpha(0.35), outline: Color.CYAN };
}

function colorForRiskLevel(level: number | null | undefined): Color {
  const severity = riskSeverityForLevel(level);
  if (severity === 'high') return Color.RED;
  if (severity === 'medium') return Color.ORANGE;
  if (severity === 'low') return Color.YELLOW;
  return Color.CYAN;
}

function ringToCartesian(positions: LonLat[]): Cartesian3[] {
  return positions.map((pos) => Cartesian3.fromDegrees(pos.lon, pos.lat));
}

function bboxToPolygonHierarchy(bbox: BBox): PolygonHierarchy {
  const positions = [
    Cartesian3.fromDegrees(bbox.min_x, bbox.min_y),
    Cartesian3.fromDegrees(bbox.max_x, bbox.min_y),
    Cartesian3.fromDegrees(bbox.max_x, bbox.max_y),
    Cartesian3.fromDegrees(bbox.min_x, bbox.max_y),
  ];
  return new PolygonHierarchy(positions);
}

function polygonHierarchiesForHazard(hazard: ProductHazardDetail): PolygonHierarchy[] {
  const polygons = extractGeoJsonPolygons(hazard.geometry);
  if (polygons.length === 0) {
    return [bboxToPolygonHierarchy(hazard.bbox)];
  }

  return polygons.map((poly) => {
    const holes = poly.holes
      .map((hole) => new PolygonHierarchy(ringToCartesian(hole)))
      .filter((hierarchy) => hierarchy.positions.length > 2);
    return new PolygonHierarchy(ringToCartesian(poly.outer), holes);
  });
}

function clampNumber(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.max(min, Math.min(max, value));
}

function isCloudCoverVariable(variable: string): boolean {
  return variable.trim().toLowerCase() === 'tcc';
}

function cameraPitchForPerspective(cameraPerspectiveId: CameraPerspectiveId): number | null {
  if (cameraPerspectiveId === 'upward') return LOCAL_UPWARD_PITCH;
  if (cameraPerspectiveId === 'forward' || cameraPerspectiveId === 'human') return LOCAL_FORWARD_PITCH;
  return null;
}

function getViewerCameraHeightMeters(viewer: CesiumViewerInstance): number | null {
  const camera = viewer.camera as unknown as { positionCartographic?: { height?: number } };
  const height = camera.positionCartographic?.height;
  if (typeof height !== 'number' || !Number.isFinite(height)) return null;
  return height;
}

type RiskClusterConfig = {
  enabled: boolean;
  pixelRange: number;
  minimumClusterSize: number;
};

function riskClusterConfigForHeight(heightMeters: number | null): RiskClusterConfig {
  if (heightMeters == null) {
    return { enabled: true, pixelRange: 60, minimumClusterSize: 2 };
  }
  if (heightMeters > 8_000_000) {
    return { enabled: true, pixelRange: 90, minimumClusterSize: 2 };
  }
  if (heightMeters > 2_000_000) {
    return { enabled: true, pixelRange: 80, minimumClusterSize: 2 };
  }
  if (heightMeters > 600_000) {
    return { enabled: true, pixelRange: 60, minimumClusterSize: 2 };
  }
  if (heightMeters > 200_000) {
    return { enabled: true, pixelRange: 40, minimumClusterSize: 3 };
  }
  return { enabled: false, pixelRange: 0, minimumClusterSize: 2 };
}

function applyRiskClusterConfig(
  clustering: { enabled: boolean; pixelRange: number; minimumClusterSize: number },
  next: RiskClusterConfig,
): boolean {
  const didChange =
    clustering.enabled !== next.enabled ||
    clustering.pixelRange !== next.pixelRange ||
    clustering.minimumClusterSize !== next.minimumClusterSize;
  clustering.enabled = next.enabled;
  clustering.pixelRange = next.pixelRange;
  clustering.minimumClusterSize = next.minimumClusterSize;
  return didChange;
}

function setupRiskPoiClustering(
  viewer: CesiumViewerInstance,
  dataSource: CustomDataSource,
): () => void {
  const clustering = dataSource.clustering as unknown as {
    enabled: boolean;
    pixelRange: number;
    minimumClusterSize: number;
    clusterEvent: { addEventListener: (fn: unknown) => void; removeEventListener: (fn: unknown) => void };
  };

  const onCluster = (
    clusteredEntities: unknown[],
    cluster: {
      label?: {
        show?: boolean;
        text?: string;
        fillColor?: unknown;
        showBackground?: boolean;
        backgroundColor?: unknown;
        disableDepthTestDistance?: number;
      };
      point?: {
        show?: boolean;
        pixelSize?: number;
        color?: unknown;
        outlineColor?: unknown;
        outlineWidth?: number;
        disableDepthTestDistance?: number;
      };
      billboard?: { show?: boolean };
    },
  ) => {
    if (cluster.billboard) cluster.billboard.show = false;
    if (cluster.point) {
      cluster.point.show = true;
      cluster.point.pixelSize = 18;
      cluster.point.color = Color.CYAN.withAlpha(0.85);
      cluster.point.outlineColor = Color.WHITE.withAlpha(0.9);
      cluster.point.outlineWidth = 2;
      cluster.point.disableDepthTestDistance = Number.POSITIVE_INFINITY;
    }
    if (cluster.label) {
      cluster.label.show = true;
      cluster.label.text = String(clusteredEntities.length);
      cluster.label.fillColor = Color.WHITE;
      cluster.label.showBackground = true;
      cluster.label.backgroundColor = Color.BLACK.withAlpha(0.55);
      cluster.label.disableDepthTestDistance = Number.POSITIVE_INFINITY;
    }
  };

  clustering.clusterEvent.addEventListener(onCluster);

  const update = () => {
    const heightMeters = getViewerCameraHeightMeters(viewer);
    const didChange = applyRiskClusterConfig(clustering, riskClusterConfigForHeight(heightMeters));
    if (didChange) {
      viewer.scene.requestRender();
    }
  };

  viewer.camera.changed.addEventListener(update);
  viewer.camera.moveEnd.addEventListener(update);
  update();

  return () => {
    viewer.camera.changed.removeEventListener(update);
    viewer.camera.moveEnd.removeEventListener(update);
    clustering.clusterEvent.removeEventListener(onCluster);
  };
}

function localFrustumForCameraHeight(heightMeters: number): { near: number; far: number } {
  const near = clampNumber(heightMeters * 0.0005, 0.2, 5);
  const far = clampNumber(heightMeters * 400, 50_000, 2_000_000);
  return { near, far: Math.max(far, near + 1) };
}

function localHumanFrustumForCameraHeight(heightMeters: number): { near: number; far: number } {
  const near = clampNumber(heightMeters * 0.0005, 0.05, 0.2);
  const far = clampNumber(heightMeters * 400, 10_000, 50_000);
  return { near, far: Math.max(far, near + 1) };
}

function localFogDensityForCameraHeight(heightMeters: number): number {
  const normalized = clampNumber(heightMeters / 12_000, 0, 1);
  return 0.00055 * (1 - normalized) + 0.00005;
}

type FlyToRequest = {
  destination: unknown;
  orientation: { heading: number; pitch: number; roll: number };
  duration: number;
};

function flyCameraToAsync(camera: CesiumViewerInstance['camera'], request: FlyToRequest): Promise<void> {
  return new Promise((resolve) => {
    camera.flyTo({
      destination: request.destination,
      orientation: request.orientation,
      duration: request.duration,
      complete: () => resolve(),
      cancel: () => resolve(),
    } as never);
  });
}

async function sampleGroundHeightMeters(
  viewer: CesiumViewerInstance,
  target: { lon: number; lat: number },
): Promise<number | null> {
  const { lon, lat } = target;

  try {
    const samples = await sampleTerrainMostDetailed(viewer.terrainProvider, [Cartographic.fromDegrees(lon, lat)]);
    const sampled = samples?.[0] as (Cartographic & { height?: number }) | undefined;
    const sampledHeight = sampled?.height;
    if (typeof sampledHeight === 'number' && Number.isFinite(sampledHeight)) return sampledHeight;
  } catch (error: unknown) {
    console.warn('[Digital Earth] failed to sample terrain most detailed', error);
  }

  const globe = (viewer.scene as unknown as { globe?: { getHeight?: (pos: unknown) => unknown } }).globe;
  const fallback = globe?.getHeight?.(Cartographic.fromDegrees(lon, lat));
  if (typeof fallback === 'number' && Number.isFinite(fallback)) return fallback;

  return null;
}

function wrapLongitudeDegrees(lon: number): number {
  if (!Number.isFinite(lon)) return 0;
  return ((lon + 180) % 360 + 360) % 360 - 180;
}

function clampLatitudeDegrees(lat: number): number {
  if (!Number.isFinite(lat)) return 0;
  if (lat < -90) return -90;
  if (lat > 90) return 90;
  return lat;
}

function deltaLongitudeDegrees(a: number, b: number): number {
  const d = a - b;
  return ((d + 540) % 360) - 180;
}

function sampleWindVectorAt(
  vectors: WindVector[],
  target: { lon: number; lat: number },
): { speedMps: number; directionDeg: number | null } | null {
  if (vectors.length === 0) return null;

  const lon = wrapLongitudeDegrees(target.lon);
  const lat = clampLatitudeDegrees(target.lat);

  const candidates = vectors
    .map((vector) => {
      const dx = deltaLongitudeDegrees(lon, vector.lon);
      const dy = lat - vector.lat;
      const dist2 = dx * dx + dy * dy;
      return { vector, dist2 };
    })
    .sort((a, b) => a.dist2 - b.dist2)
    .slice(0, 8);

  if (candidates.length === 0) return null;
  if (candidates[0]!.dist2 <= 0) {
    const { u, v } = candidates[0]!.vector;
    const speedMps = Math.sqrt(u * u + v * v);
    const directionDeg =
      speedMps > 0 ? ((Math.atan2(u, v) * 180) / Math.PI + 360) % 360 : null;
    return { speedMps, directionDeg };
  }

  const epsilon = 1e-12;
  let sumW = 0;
  let sumU = 0;
  let sumV = 0;

  for (const { vector, dist2 } of candidates) {
    const weight = 1 / Math.max(epsilon, dist2);
    sumW += weight;
    sumU += vector.u * weight;
    sumV += vector.v * weight;
  }

  if (!Number.isFinite(sumW) || sumW <= 0) return null;

  const u = sumU / sumW;
  const v = sumV / sumW;
  const speedMps = Math.sqrt(u * u + v * v);
  const directionDeg =
    speedMps > 0 ? ((Math.atan2(u, v) * 180) / Math.PI + 360) % 360 : null;

  return { speedMps, directionDeg };
}

function toUtcIsoNoMillis(date: Date): string {
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

function makeHourlyUtcIso(baseUtcIso: string, frameIndex: number): string {
  const base = new Date(baseUtcIso);
  if (Number.isNaN(base.getTime())) return baseUtcIso;

  const normalized =
    ((frameIndex % CLOUD_LAYER_FRAME_COUNT) + CLOUD_LAYER_FRAME_COUNT) %
    CLOUD_LAYER_FRAME_COUNT;
  return toUtcIsoNoMillis(new Date(base.getTime() + normalized * CLOUD_LAYER_FRAME_STEP_MS));
}

function sortByZIndex(a: { zIndex: number; id: string }, b: { zIndex: number; id: string }): number {
  return a.zIndex - b.zIndex || a.id.localeCompare(b.id);
}

function cloneLayerConfigs(configs: LayerConfig[]): LayerConfig[] {
  return configs.map((layer) => ({ ...layer }));
}

function historicalStatisticsFiltersForEvent(eventType: string): {
  source: string;
  variable: string | null;
  window_kind: string;
} {
  const canonicalType = canonicalizeEventType(eventType);
  if (canonicalType === 'snow') {
    return { source: 'cldas', variable: 'SNOWFALL', window_kind: 'rolling_days' };
  }
  return { source: 'cldas', variable: null, window_kind: 'rolling_days' };
}

function scoreBiasLayerForEvent(eventType: string, layer: string): number {
  const canonicalType = canonicalizeEventType(eventType);
  const normalizedLayer = layer.trim().toLowerCase();

  if (canonicalType) {
    if (normalizedLayer === `bias/${canonicalType}`) return 0;
    if (
      canonicalType === 'snow' &&
      (normalizedLayer.includes('snow') || normalizedLayer.includes('snod') || normalizedLayer.includes('snowfall'))
    ) {
      return 1;
    }
    if (normalizedLayer.includes(canonicalType)) return 2;
  }

  if (normalizedLayer === 'bias/temp') return 10;
  return 100;
}

function pickBiasLayerForEvent(eventType: string, candidates: string[]): string | null {
  const normalizedCandidates = candidates.map((layer) => layer.trim()).filter((layer) => layer.length > 0);
  if (normalizedCandidates.length === 0) return null;

  const scored = normalizedCandidates
    .map((layer) => ({ layer, score: scoreBiasLayerForEvent(eventType, layer) }))
    .sort((a, b) => a.score - b.score || a.layer.localeCompare(b.layer));

  return scored[0]!.layer;
}

function clearAnalyticsLayerRef(ref: { current: AnalyticsTileLayer | null }) {
  ref.current?.destroy();
  ref.current = null;
}

function upsertAnalyticsTileLayer(
  viewer: CesiumViewerInstance,
  ref: { current: AnalyticsTileLayer | null },
  params: AnalyticsTileLayerParams,
) {
  const current = ref.current;
  if (current) {
    current.update(params);
  } else {
    ref.current = new AnalyticsTileLayer(viewer, params);
  }

  const layer = ref.current?.layer;
  if (layer) viewer.imageryLayers.raiseToTop(layer);
}

function useEventAnalyticsTileLayer(options: {
  viewer: CesiumViewerInstance | null;
  apiBaseUrl: string | null;
  active: boolean;
  layerRef: { current: AnalyticsTileLayer | null };
  setStatus: (status: EventLayerModeStatus) => void;
  load: (options: { apiBaseUrl: string; signal: AbortSignal }) => Promise<AnalyticsTileLayerParams | null>;
  logLabel: string;
}) {
  const { viewer, apiBaseUrl, active, layerRef, setStatus, load, logLabel } = options;

  useEffect(() => {
    if (!viewer || !apiBaseUrl || !active) {
      clearAnalyticsLayerRef(layerRef);
      setStatus('idle');
      return;
    }

    const controller = new AbortController();
    setStatus('loading');

    void (async () => {
      try {
        const params = await load({ apiBaseUrl, signal: controller.signal });
        if (controller.signal.aborted) return;

        if (!params) {
          clearAnalyticsLayerRef(layerRef);
          setStatus('error');
          return;
        }

        upsertAnalyticsTileLayer(viewer, layerRef, params);
        setStatus('loaded');
      } catch (error) {
        if (controller.signal.aborted) return;
        console.warn(`[Digital Earth] failed to load ${logLabel}`, error);
        clearAnalyticsLayerRef(layerRef);
        setStatus('error');
      }
    })();

    return () => controller.abort();
  }, [active, apiBaseUrl, layerRef, load, logLabel, setStatus, viewer]);
}

type SavedCameraState = {
  lon: number;
  lat: number;
  heightMeters: number;
  heading: number;
  pitch: number;
  roll: number;
};

type ModeSnapshot = {
  layers: LayerConfig[];
  cloudFrameIndex: number;
  camera: SavedCameraState | null;
};

function snapshotViewerCamera(viewer: CesiumViewerInstance): SavedCameraState | null {
  const camera = viewer.camera as unknown as {
    positionCartographic?: { longitude?: number; latitude?: number; height?: number };
    heading?: number;
    pitch?: number;
    roll?: number;
  };

  const cartographic = camera.positionCartographic;
  const lonRad = cartographic?.longitude;
  const latRad = cartographic?.latitude;
  const heightMeters = cartographic?.height;
  if (typeof lonRad !== 'number' || !Number.isFinite(lonRad)) return null;
  if (typeof latRad !== 'number' || !Number.isFinite(latRad)) return null;
  if (typeof heightMeters !== 'number' || !Number.isFinite(heightMeters)) return null;

  const heading = camera.heading;
  const pitch = camera.pitch;
  const roll = camera.roll;
  if (typeof heading !== 'number' || !Number.isFinite(heading)) return null;
  if (typeof pitch !== 'number' || !Number.isFinite(pitch)) return null;
  if (typeof roll !== 'number' || !Number.isFinite(roll)) return null;

  return {
    lon: wrapLongitudeDegrees(CesiumMath.toDegrees(lonRad)),
    lat: clampLatitudeDegrees(CesiumMath.toDegrees(latRad)),
    heightMeters,
    heading,
    pitch,
    roll,
  };
}

function isE2eEnabled(): boolean {
  const raw = import.meta.env.VITE_E2E;
  if (!raw) return false;
  const normalized = raw.trim().toLowerCase();
  return normalized === 'true' || normalized === '1' || normalized === 'yes';
}

export function CesiumViewer() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [viewer, setViewer] = useState<CesiumViewerInstance | null>(null);
  const [mapConfig, setMapConfig] = useState<MapConfig | undefined>(undefined);
  const [mapConfigLoaded, setMapConfigLoaded] = useState(false);
  const [apiBaseUrl, setApiBaseUrl] = useState<string | null>(null);
  const [terrainNotice, setTerrainNotice] = useState<string | null>(null);
  const [terrainReady, setTerrainReady] = useState(false);
  const [monitoringNotice, setMonitoringNotice] = useState<string | null>(null);
  const [performanceNotice, setPerformanceNotice] = useState<{ fps: number } | null>(null);
  const basemapId = useBasemapStore((state) => state.basemapId);
  const sceneModeId = useSceneModeStore((state) => state.sceneModeId);
  const viewModeRoute = useViewModeStore((state) => state.route);
  const viewModeTransition = useViewModeStore((state) => state.transition);
  const enterLocal = useViewModeStore((state) => state.enterLocal);
  const enterLayerGlobal = useViewModeStore((state) => state.enterLayerGlobal);
  const canGoBack = useViewModeStore((state) => state.canGoBack);
  const goBack = useViewModeStore((state) => state.goBack);
  const replaceRoute = useViewModeStore((state) => state.replaceRoute);
  const layers = useLayerManagerStore((state) => state.layers);
  const runTimeKey = useTimeStore((state) => state.runTimeKey);
  const timeKey = useTimeStore((state) => state.timeKey);
  const levelKey = useTimeStore((state) => state.levelKey);
  const eventLayersEnabled = useEventLayersStore((state) => state.enabled);
  const eventLayersMode = useEventLayersStore((state) => state.mode);
  const performanceMode = usePerformanceModeStore((state) => state.mode);
  const lowModeEnabled = performanceMode === 'low';
  const setPerformanceMode = usePerformanceModeStore((state) => state.setMode);
  const infoPanelCollapsed = useLayoutPanelsStore((state) => state.infoPanelCollapsed);
  const osmBuildingsEnabled = useOsmBuildingsStore((state) => state.enabled);
  const cameraPerspectiveId = useCameraPerspectiveStore((state) => state.cameraPerspectiveId);
  const appliedBasemapIdRef = useRef<BasemapId | null>(null);
  const didApplySceneModeRef = useRef(false);
  const localEntryKeyRef = useRef<string | null>(null);
  const localHumanEntryKeyRef = useRef<string | null>(null);
  const localHumanLandingAbortRef = useRef<AbortController | null>(null);
  const localTerrainSamplePromiseRef = useRef<{
    key: string | null;
    promise: Promise<number | null> | null;
  }>({ key: null, promise: null });
  const layerGlobalEntryKeyRef = useRef<string | null>(null);
  const eventEntryKeyRef = useRef<string | null>(null);
  const appliedCameraPerspectiveRef = useRef<CameraPerspectiveId | null>(null);
  const eventAbortRef = useRef<AbortController | null>(null);
  const eventEntitiesRef = useRef<Entity[]>([]);
  const cachedIonTerrainRef = useRef<{ token: string; provider: unknown } | null>(null);
  const cachedSelfHostedTerrainRef = useRef<{ terrainUrl: string; provider: unknown } | null>(null);
  const localTerrainSampleKeyRef = useRef<string | null>(null);
  const riskAbortRef = useRef<AbortController | null>(null);
  const riskEntryKeyRef = useRef<string | null>(null);
  const riskDataSourceRef = useRef<CustomDataSource | null>(null);
  const riskClusterTeardownRef = useRef<(() => void) | null>(null);
  const riskPoisByIdRef = useRef<Map<number, RiskPOI>>(new Map());
  const riskEvalByIdRef = useRef<Map<number, POIRiskResult>>(new Map());
  const riskPopupAbortRef = useRef<AbortController | null>(null);
  const baseCameraControllerRef = useRef<{
    enableTilt?: boolean;
    enableLook?: boolean;
    enableRotate?: boolean;
    rotateEventTypes?: unknown;
    lookEventTypes?: unknown;
  } | null>(null);
  const baseLocalEnvironmentRef = useRef<{
    fog?: {
      enabled?: boolean;
      density?: number;
      screenSpaceErrorFactor?: number;
      minimumBrightness?: number;
    };
    skyBoxShow?: boolean;
    skyAtmosphereShow?: boolean;
    frustum?: { near?: number; far?: number; fov?: number };
  } | null>(null);
  const temperatureLayersRef = useRef<Map<string, TemperatureLayer>>(new Map());
  const cloudLayersRef = useRef<Map<string, CloudLayer>>(new Map());
  const localCloudStackRef = useRef<LocalCloudStack | null>(null);
  const precipitationLayersRef = useRef<Map<string, PrecipitationLayer>>(new Map());
  const snowDepthLayersRef = useRef<Map<string, SnowDepthLayer>>(new Map());
  const eventHistoricalLayerRef = useRef<AnalyticsTileLayer | null>(null);
  const eventBiasLayerRef = useRef<AnalyticsTileLayer | null>(null);
  const precipitationParticlesRef = useRef<PrecipitationParticles | null>(null);
  const windArrowsRef = useRef<WindArrows | null>(null);
  const windAbortRef = useRef<AbortController | null>(null);
  const windVectorsRef = useRef<WindVector[]>([]);
  const windViewKeyRef = useRef<string | null>(null);
  const windVectorsKeyRef = useRef<string | null>(null);
  const windStyleKeyRef = useRef<string | null>(null);
  const windVectorsCacheRef = useRef<Map<string, WindVector[]>>(new Map());
  const weatherSamplerRef = useRef<ReturnType<typeof createWeatherSampler> | null>(null);
  const weatherAbortRef = useRef<AbortController | null>(null);
  const cloudSamplerRef = useRef<ReturnType<typeof createCloudSampler> | null>(null);
  const samplingAbortRef = useRef<AbortController | null>(null);
  const osmBuildingsTilesetRef = useRef<Cesium3DTileset | null>(null);
  const osmBuildingsLoadingRef = useRef<Promise<Cesium3DTileset> | null>(null);
  const osmBuildingsTilesetCleanupRef = useRef<(() => void) | null>(null);
  const [cloudFrameIndex, setCloudFrameIndex] = useState(0);
  const [eventMonitoringTimeKey, setEventMonitoringTimeKey] = useState<string | null>(null);
  const [eventMonitoringRectangle, setEventMonitoringRectangle] = useState<{
    west: number;
    south: number;
    east: number;
    north: number;
  } | null>(null);
  const [eventHistoricalLayerStatus, setEventHistoricalLayerStatus] =
    useState<EventLayerModeStatus>('idle');
  const [eventBiasLayerStatus, setEventBiasLayerStatus] = useState<EventLayerModeStatus>('idle');
  const [eventTitle, setEventTitle] = useState<string | null>(null);
  const [riskPopup, setRiskPopup] = useState<{
    poi: RiskPOI;
    evaluation: POIRiskResult | null;
    status: 'loading' | 'loaded' | 'error';
    errorMessage: string | null;
  } | null>(null);
  const [disasterDemoOpen, setDisasterDemoOpen] = useState(false);
  const localModeSnapshotRef = useRef<ModeSnapshot | null>(null);
  const pendingLocalCameraRestoreRef = useRef<SavedCameraState | null>(null);
  const previousRouteRef = useRef<ViewModeRoute | null>(null);
  const eventModeLayersSnapshotRef = useRef<LayerConfig[] | null>(null);
  const eventMonitoringLayersSnapshotRef = useRef<Map<string, boolean> | null>(null);
  const eventAutoLayerTypeRef = useRef<string | null>(null);
  const eventAutoLayerAppliedRef = useRef(false);
  const eventAutoLayerProductIdRef = useRef<string | null>(null);
  const {
    state: samplingCardState,
    open: openSamplingCard,
    close: closeSamplingCard,
    setData: setSamplingData,
    setError: setSamplingError,
  } = useSamplingCard();
  const cloudTimeKey = useMemo(
    () => makeHourlyUtcIso(timeKey, cloudFrameIndex),
    [cloudFrameIndex, timeKey],
  );

  const requestLocalGroundHeightMeters = useCallback(
    (target: { lon: number; lat: number }): Promise<number | null> => {
      if (!viewer) return Promise.resolve(null);

      const key = `${target.lon}:${target.lat}`;
      const existing = localTerrainSamplePromiseRef.current;
      if (existing.key === key && existing.promise) return existing.promise;

      const promise = sampleGroundHeightMeters(viewer, target).catch(() => null);
      localTerrainSamplePromiseRef.current = { key, promise };
      return promise;
    },
    [viewer],
  );

  useEffect(() => {
    localTerrainSamplePromiseRef.current = { key: null, promise: null };
  }, [terrainReady]);

  useEffect(() => {
    if (!viewer) return;
    if (!isE2eEnabled()) return;

    const api = {
      getEventEntityIds: () => eventEntitiesRef.current.map((entity) => String(entity.id)),
      getRiskPoiIds: () => Array.from(riskPoisByIdRef.current.keys()),
      getRiskPoiCanvasPosition: (poiId: number) => {
        const dataSource = riskDataSourceRef.current;
        if (!dataSource) return null;
        const entity = dataSource.entities.getById(`risk-poi:${poiId}`);
        if (!entity) return null;

        const position = entity.position?.getValue(viewer.clock.currentTime);
        if (!position) return null;

        const canvasCoords = SceneTransforms.worldToWindowCoordinates(viewer.scene, position);
        if (!canvasCoords) return null;

        const x = canvasCoords.x;
        const y = canvasCoords.y;
        if (!Number.isFinite(x) || !Number.isFinite(y)) return null;

        const canvas = viewer.scene.canvas;
        const width = canvas.clientWidth || canvas.width;
        const height = canvas.clientHeight || canvas.height;
        if (width && (x < 0 || x > width)) return null;
        if (height && (y < 0 || y > height)) return null;

        return { x, y };
      },
      isLayerGlobalShellActive: () => {
        const provider = viewer.terrainProvider as unknown as {
          tilingScheme?: { ellipsoid?: { radii?: { x?: number } } };
        };
        const radiiX = provider.tilingScheme?.ellipsoid?.radii?.x;
        if (typeof radiiX !== 'number' || !Number.isFinite(radiiX)) return false;
        const offsetMeters = radiiX - Ellipsoid.WGS84.radii.x;
        return offsetMeters > 1;
      },
    } satisfies NonNullable<Window['__DIGITAL_EARTH_E2E__']>;

    window.__DIGITAL_EARTH_E2E__ = api;
    return () => {
      if (window.__DIGITAL_EARTH_E2E__ === api) {
        delete window.__DIGITAL_EARTH_E2E__;
      }
    };
  }, [viewer]);

  const maybeApplyEventAutoLayerTemplate = useCallback(() => {
    if (useViewModeStore.getState().route.viewModeId !== 'event') return;
    if (eventAutoLayerAppliedRef.current) return;

    const eventType = eventAutoLayerTypeRef.current?.trim() ?? '';
    if (!eventType) return;

    const layerManager = useLayerManagerStore.getState();
    const availableLayerIds = layerManager.layers.map((layer) => layer.id);

    const templateSpec = useEventAutoLayersStore.getState().getTemplateSpecForEvent(eventType);
    if (!templateSpec) {
      eventAutoLayerAppliedRef.current = true;
      return;
    }

    const templateLayerIds = resolveEventLayerTemplateSpec(templateSpec, availableLayerIds);
    if (templateLayerIds.length === 0) {
      return;
    }

    if (!eventModeLayersSnapshotRef.current && layerManager.layers.length > 0) {
      eventModeLayersSnapshotRef.current = cloneLayerConfigs(layerManager.layers);
    }

    layerManager.batch(() => {
      for (const layer of layerManager.layers) {
        if (!layer.visible) continue;
        layerManager.setLayerVisible(layer.id, false);
      }
      for (const id of templateLayerIds) {
        layerManager.setLayerVisible(id, true);
      }
    });

    eventAutoLayerAppliedRef.current = true;
  }, []);

  const activeLayer = useMemo(() => {
    const visible = layers.filter((layer) => layer.visible).sort(sortByZIndex);
    return visible.length > 0 ? visible[visible.length - 1]! : null;
  }, [layers]);

  const localTimeKey = useMemo(() => {
    if (activeLayer?.type === 'cloud') return cloudTimeKey;
    return timeKey;
  }, [activeLayer, cloudTimeKey, timeKey]);

  const snowDepthTimeKey = useMemo(() => {
    if (viewModeRoute.viewModeId === 'event' && eventMonitoringTimeKey) {
      return eventMonitoringTimeKey;
    }
    return timeKey;
  }, [eventMonitoringTimeKey, timeKey, viewModeRoute.viewModeId]);

  const layerGlobalLayerId =
    viewModeRoute.viewModeId === 'layerGlobal' ? viewModeRoute.layerId : null;
  const layerGlobalShellHeightMeters = useMemo(() => {
    if (!layerGlobalLayerId) return null;
    const targetLayer = layers.find((layer) => layer.id === layerGlobalLayerId) ?? null;
    return targetLayer
      ? LAYER_GLOBAL_SHELL_HEIGHT_METERS_BY_LAYER_TYPE[targetLayer.type]
      : LAYER_GLOBAL_SHELL_HEIGHT_METERS_BY_LAYER_TYPE.cloud;
  }, [layerGlobalLayerId, layers]);

  const basemapProvider = mapConfig?.basemapProvider ?? 'open';

  useLayoutEffect(() => {
    const prev = previousRouteRef.current;
    const next = viewModeRoute;
    previousRouteRef.current = next;

    if (!prev) {
      if (next.viewModeId === 'event') {
        eventAutoLayerTypeRef.current = null;
        eventAutoLayerAppliedRef.current = false;
        eventModeLayersSnapshotRef.current = null;
      }
      return;
    }

    if (prev.viewModeId === 'local' && next.viewModeId === 'layerGlobal') {
      localModeSnapshotRef.current = {
        layers: useLayerManagerStore.getState().layers.map((layer) => ({ ...layer })),
        cloudFrameIndex,
        camera: viewer ? snapshotViewerCamera(viewer) : null,
      };
      return;
    }

    if (prev.viewModeId === 'layerGlobal' && next.viewModeId === 'local') {
      const isBack =
        viewModeTransition?.kind === 'back' &&
        viewModeTransition.from.viewModeId === 'layerGlobal' &&
        viewModeTransition.to.viewModeId === 'local';
      if (!isBack) return;

      const snapshot = localModeSnapshotRef.current;
      if (!snapshot) return;

      useLayerManagerStore.getState().batch(() => {
        useLayerManagerStore.setState({ layers: snapshot.layers });
      });

      if (!Object.is(cloudFrameIndex, snapshot.cloudFrameIndex)) {
        setCloudFrameIndex(snapshot.cloudFrameIndex);
      }

      pendingLocalCameraRestoreRef.current = snapshot.camera;
    }

    if (prev.viewModeId !== 'event' && next.viewModeId === 'event') {
      eventAutoLayerTypeRef.current = null;
      eventAutoLayerAppliedRef.current = false;

      const currentLayers = useLayerManagerStore.getState().layers;
      eventModeLayersSnapshotRef.current =
        currentLayers.length > 0 ? cloneLayerConfigs(currentLayers) : null;
      return;
    }

    if (prev.viewModeId === 'event' && next.viewModeId !== 'event') {
      const snapshot = eventModeLayersSnapshotRef.current;
      eventModeLayersSnapshotRef.current = null;
      eventAutoLayerTypeRef.current = null;
      eventAutoLayerAppliedRef.current = false;

      const shouldRestore = useEventAutoLayersStore.getState().restoreOnExit;
      if (!shouldRestore || !snapshot) return;

      useLayerManagerStore.getState().batch(() => {
        useLayerManagerStore.setState({ layers: snapshot });
      });
    }
  }, [cloudFrameIndex, viewModeRoute, viewModeTransition, viewer]);

  useEffect(() => {
    maybeApplyEventAutoLayerTemplate();
  }, [layers, maybeApplyEventAutoLayerTemplate]);

  useEffect(() => {
    if (viewModeRoute.viewModeId !== 'event') {
      eventMonitoringLayersSnapshotRef.current = null;
      return;
    }

    const shouldShowMonitoringLayers = eventLayersEnabled && eventLayersMode === 'monitoring';
    const layerManager = useLayerManagerStore.getState();

    if (shouldShowMonitoringLayers) {
      const snapshot = eventMonitoringLayersSnapshotRef.current;
      if (!snapshot) return;

      layerManager.batch(() => {
        for (const [id, visible] of snapshot.entries()) {
          layerManager.setLayerVisible(id, visible);
        }
      });
      eventMonitoringLayersSnapshotRef.current = null;
      return;
    }

    const hasVisibleMonitoringLayers = layers.some((layer) => layer.visible);
    if (!hasVisibleMonitoringLayers) return;

    eventMonitoringLayersSnapshotRef.current = new Map(layers.map((layer) => [layer.id, layer.visible]));
    layerManager.batch(() => {
      for (const layer of layerManager.layers) {
        if (!layer.visible) continue;
        layerManager.setLayerVisible(layer.id, false);
      }
    });
  }, [eventLayersEnabled, eventLayersMode, layers, viewModeRoute.viewModeId]);

  useEffect(() => {
    if (!viewer) return;

    if (!baseCameraControllerRef.current) {
      const controller = viewer.scene.screenSpaceCameraController as unknown as {
        enableTilt?: boolean;
        enableLook?: boolean;
        enableRotate?: boolean;
        rotateEventTypes?: unknown;
        lookEventTypes?: unknown;
      };
      baseCameraControllerRef.current = {
        enableTilt: controller.enableTilt,
        enableLook: controller.enableLook,
        enableRotate: controller.enableRotate,
        rotateEventTypes: controller.rotateEventTypes,
        lookEventTypes: controller.lookEventTypes,
      };
    }

    if (!baseLocalEnvironmentRef.current) {
      const scene = viewer.scene as unknown as {
        fog?: {
          enabled?: boolean;
          density?: number;
          screenSpaceErrorFactor?: number;
          minimumBrightness?: number;
        };
        skyBox?: { show?: boolean };
        skyAtmosphere?: { show?: boolean };
      };
      const frustum = viewer.camera.frustum as unknown as { near?: number; far?: number; fov?: number };

      baseLocalEnvironmentRef.current = {
        fog: scene.fog
          ? {
              enabled: scene.fog.enabled,
              density: scene.fog.density,
              screenSpaceErrorFactor: scene.fog.screenSpaceErrorFactor,
              minimumBrightness: scene.fog.minimumBrightness,
            }
          : undefined,
        skyBoxShow: scene.skyBox?.show,
        skyAtmosphereShow: scene.skyAtmosphere?.show,
        frustum: {
          near: frustum?.near,
          far: frustum?.far,
          fov: frustum?.fov,
        },
      };
    }
  }, [viewer]);

  useEffect(() => {
    let cancelled = false;
    void loadConfig()
      .then((config) => {
        if (cancelled) return;
        setMapConfig(config.map);
        setApiBaseUrl(config.apiBaseUrl);
      })
      .catch(() => {
        if (cancelled) return;
        setMapConfig(undefined);
        setApiBaseUrl(null);
      })
      .finally(() => {
        if (cancelled) return;
        setMapConfigLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const defaultDestination = Cartesian3.fromDegrees(
      DEFAULT_CAMERA.longitude,
      DEFAULT_CAMERA.latitude,
      DEFAULT_CAMERA.heightMeters
    );

    const initialBasemapId = useBasemapStore.getState().basemapId;
    const selectedBasemap = getBasemapById(initialBasemapId);
    if (!selectedBasemap) {
      throw new Error(`Unknown basemap id: ${initialBasemapId}`);
    }

    const e2eMode = isE2eEnabled();
    const fallbackBasemap = getBasemapById(DEFAULT_BASEMAP_ID);
    if (!fallbackBasemap || fallbackBasemap.kind === 'ion') {
      throw new Error(`Invalid default basemap config: ${DEFAULT_BASEMAP_ID}`);
    }

    const needsFallbackBasemap = selectedBasemap.kind === 'ion';
    const initialBaseLayerBasemap = needsFallbackBasemap ? fallbackBasemap : selectedBasemap;

    appliedBasemapIdRef.current = e2eMode
      ? initialBasemapId
      : needsFallbackBasemap
        ? DEFAULT_BASEMAP_ID
        : initialBasemapId;

    const imageryProvider = e2eMode
      ? new UrlTemplateImageryProvider({
          url: `${window.location.origin}/api/v1/tiles/e2e/{z}/{x}/{y}.png`,
          tilingScheme: new WebMercatorTilingScheme(),
          maximumLevel: 0,
        })
      : createImageryProviderForBasemap(initialBaseLayerBasemap);

    const newViewer = new Viewer(containerRef.current!, {
      baseLayer: new ImageryLayer(
        // Avoid Cesium ion default imagery (Bing) by always passing an explicit base layer.
        imageryProvider,
      ),
      baseLayerPicker: false,
      geocoder: false,
      animation: false,
      timeline: false,
      fullscreenButton: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      infoBox: false,
      selectionIndicator: false,
      homeButton: true
    });

    newViewer.scene.requestRenderMode = true;
    newViewer.scene.maximumRenderTimeChange = Infinity;

    newViewer.camera.setView({ destination: defaultDestination });

    const controller = newViewer.scene.screenSpaceCameraController;
    controller.minimumZoomDistance = MIN_ZOOM_DISTANCE_METERS;
    controller.maximumZoomDistance = MAX_ZOOM_DISTANCE_METERS;

    newViewer.homeButton.viewModel.command.beforeExecute.addEventListener((e) => {
      e.cancel = true;
      newViewer.camera.flyTo({ destination: defaultDestination, duration: 0.8 });
    });

    setViewer(newViewer);

    return () => {
      riskClusterTeardownRef.current?.();
      riskClusterTeardownRef.current = null;
      newViewer.destroy();
    };
  }, []);

  useEffect(() => {
    const token = mapConfig?.cesiumIonAccessToken;
    if (!token) return;
    Ion.defaultAccessToken = token;
  }, [mapConfig?.cesiumIonAccessToken]);

  useEffect(() => {
    if (!viewer) return;
    if (basemapProvider !== 'open') return;
    if (appliedBasemapIdRef.current === basemapId) return;
    const basemap = getBasemapById(basemapId);
    if (!basemap) return;
    if (basemap.kind === 'ion' && !mapConfig?.cesiumIonAccessToken) {
      if (!mapConfigLoaded) return;
      const fallbackBasemapId = appliedBasemapIdRef.current ?? DEFAULT_BASEMAP_ID;
      console.warn('[Digital Earth] Cesium ion basemap selected without token; reverting', {
        basemapId,
        fallbackBasemapId,
      });
      if (fallbackBasemapId !== basemapId) {
        useBasemapStore.getState().setBasemapId(fallbackBasemapId);
      }
      return;
    }

    const controller = new AbortController();

    void (async () => {
      try {
        const provider = await createImageryProviderForBasemapAsync(basemap);
        if (controller.signal.aborted) return;
        if (useBasemapStore.getState().basemapId !== basemapId) return;
        setViewerImageryProvider(viewer, provider);
        appliedBasemapIdRef.current = basemapId;
      } catch (error: unknown) {
        if (controller.signal.aborted) return;
        if (useBasemapStore.getState().basemapId !== basemapId) return;

        const fallbackBasemapId = appliedBasemapIdRef.current ?? DEFAULT_BASEMAP_ID;
        console.warn('[Digital Earth] failed to apply basemap; reverting', {
          basemapId,
          fallbackBasemapId,
          error,
        });
        if (fallbackBasemapId !== basemapId) {
          useBasemapStore.getState().setBasemapId(fallbackBasemapId);
        }
      }
    })();

    return () => {
      controller.abort();
    };
  }, [basemapId, basemapProvider, mapConfig?.cesiumIonAccessToken, mapConfigLoaded, viewer]);

  useEffect(() => {
    if (!viewer) return;
    return () => {
      osmBuildingsLoadingRef.current = null;
      osmBuildingsTilesetCleanupRef.current?.();
      osmBuildingsTilesetCleanupRef.current = null;
      const existing = osmBuildingsTilesetRef.current;
      if (!existing) return;
      osmBuildingsTilesetRef.current = null;
      try {
        viewer.scene.primitives.remove(existing);
      } catch {
        // ignore teardown errors
      }
      try {
        existing.destroy();
      } catch {
        // ignore teardown errors
      }
    };
  }, [viewer]);

  useEffect(() => {
    if (!viewer) return;
    if (!localCloudStackRef.current) {
      localCloudStackRef.current = new LocalCloudStack(viewer);
    }
    return () => {
      localCloudStackRef.current?.destroy();
      localCloudStackRef.current = null;
    };
  }, [viewer]);

  useEffect(() => {
    if (!viewer) return;

    const active =
      osmBuildingsEnabled &&
      !lowModeEnabled &&
      viewModeRoute.viewModeId !== 'layerGlobal' &&
      sceneModeId === '3d';

    const scene: Scene = viewer.scene;
    const primitives: PrimitiveCollection = scene.primitives;

    if (!active) {
      osmBuildingsLoadingRef.current = null;
      osmBuildingsTilesetCleanupRef.current?.();
      osmBuildingsTilesetCleanupRef.current = null;
      const existing = osmBuildingsTilesetRef.current;
      if (existing) {
        osmBuildingsTilesetRef.current = null;
        primitives.remove(existing);
        try {
          existing.destroy();
        } catch {
          // ignore teardown errors
        }
        scene.requestRender();
      }
      return;
    }

    const token = mapConfig?.cesiumIonAccessToken;
    if (!token) return;

    const existing = osmBuildingsTilesetRef.current;
    if (existing) {
      existing.show = true;
      scene.requestRender();
      return;
    }

    if (osmBuildingsLoadingRef.current) return;

    let cancelled = false;
    const loadPromise = createOsmBuildingsAsync();
    osmBuildingsLoadingRef.current = loadPromise;

    void loadPromise
      .then((tileset) => {
        if (cancelled) {
          tileset.destroy();
          return;
        }

        if (!Object.is(osmBuildingsLoadingRef.current, loadPromise)) {
          tileset.destroy();
          return;
        }

        osmBuildingsLoadingRef.current = null;
        osmBuildingsTilesetRef.current = tileset;
        tileset.show = true;

        osmBuildingsTilesetCleanupRef.current?.();
        const requestRender = () => {
          scene.requestRender();
        };
        tileset.loadProgress.addEventListener(requestRender);
        tileset.allTilesLoaded.addEventListener(requestRender);
        tileset.initialTilesLoaded.addEventListener(requestRender);
        osmBuildingsTilesetCleanupRef.current = () => {
          tileset.loadProgress.removeEventListener(requestRender);
          tileset.allTilesLoaded.removeEventListener(requestRender);
          tileset.initialTilesLoaded.removeEventListener(requestRender);
        };

        // Add buildings below other primitives so weather and overlays can still render on top.
        primitives.add(tileset, 0);
        scene.requestRender();
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (!Object.is(osmBuildingsLoadingRef.current, loadPromise)) return;
        osmBuildingsLoadingRef.current = null;
        console.warn('[Digital Earth] failed to load Cesium OSM Buildings', error);
      });

    return () => {
      cancelled = true;
    };
  }, [lowModeEnabled, mapConfig?.cesiumIonAccessToken, osmBuildingsEnabled, sceneModeId, viewModeRoute.viewModeId, viewer]);

  useEffect(() => {
    if (!viewer) return;

    const monitor = createFpsMonitor({ sampleWindowMs: 1000, idleResetMs: 2500 });
    const detector = createLowFpsDetector({
      thresholdFps: 30,
      consecutiveSamples: 2,
      cooldownMs: 60_000,
    });

    let lastFps: number | null = null;

    const onPostRender = () => {
      const nowMs = performance.now();
      const sampledFps = monitor.recordFrame(nowMs);
      const snapshot = monitor.getSnapshot();

      if (!Object.is(snapshot.fps, lastFps)) {
        lastFps = snapshot.fps;
        useViewerStatsStore.getState().setFps(snapshot.fps);
      }

      if (sampledFps == null) return;
      const fps = sampledFps;
      if (usePerformanceModeStore.getState().mode !== 'high') return;
      if (!detector.recordSample({ fps, nowMs })) return;
      if (typeof fps === 'number') {
        setPerformanceNotice({ fps });
      }
    };

    const scene = viewer.scene as unknown as {
      postRender?: {
        addEventListener?: (handler: () => void) => void;
        removeEventListener?: (handler: () => void) => void;
      };
    };

    scene.postRender?.addEventListener?.(onPostRender);

    return () => {
      scene.postRender?.removeEventListener?.(onPostRender);
      useViewerStatsStore.getState().setFps(null);
    };
  }, [viewer]);

  useEffect(() => {
    if (!lowModeEnabled) return;
    setPerformanceNotice(null);
  }, [lowModeEnabled]);

  useEffect(() => {
    if (!viewer) return;
    if (!mapConfig) return;

    let cancelled = false;

    const applyBasemapProvider = async () => {
      if (mapConfig.basemapProvider !== 'ion') return;
      const token = mapConfig.cesiumIonAccessToken;
      if (!token) {
        console.warn('[Digital Earth] map.basemapProvider=ion requires map.cesiumIonAccessToken');
        return;
      }
      const provider = await createWorldImageryAsync();
      if (cancelled) return;
      setViewerImageryProvider(viewer, provider);
    };

    if (mapConfig.basemapProvider === 'selfHosted') {
      const urlTemplate = mapConfig.selfHosted?.basemapUrlTemplate;
      if (!urlTemplate) {
        console.warn('[Digital Earth] map.basemapProvider=selfHosted requires map.selfHosted.basemapUrlTemplate');
      } else {
        const scheme = mapConfig.selfHosted?.basemapScheme ?? 'xyz';
        const provider = new UrlTemplateImageryProvider({
          url: normalizeTmsTemplate(urlTemplate, scheme),
          tilingScheme: new WebMercatorTilingScheme(),
          credit: 'Self-hosted basemap',
        });
        setViewerImageryProvider(viewer, provider);
      }
    }

    void applyBasemapProvider().catch((error: unknown) => {
      if (cancelled) return;
      console.warn('[Digital Earth] failed to apply basemap provider', error);
    });

    return () => {
      cancelled = true;
    };
  }, [mapConfig, viewer]);

  useEffect(() => {
    if (!viewer) return;
    if (!mapConfig) {
      setTerrainReady(false);
      return;
    }
    if (viewModeRoute.viewModeId === 'layerGlobal') return;

    let cancelled = false;

    const applyTerrainProvider = async () => {
      setTerrainNotice(null);

      const terrainProviderMode = mapConfig?.terrainProvider;

      if (terrainProviderMode === 'none' || terrainProviderMode === undefined) {
        setTerrainReady(false);
        viewer.terrainProvider = new EllipsoidTerrainProvider();
        viewer.scene.requestRender();
        return;
      }

      if (terrainProviderMode === 'ion') {
        const token = mapConfig?.cesiumIonAccessToken;
        if (!token) {
          console.warn('[Digital Earth] map.terrainProvider=ion requires map.cesiumIonAccessToken');
          setTerrainNotice('未配置 Cesium ion token，已回退到无地形模式。');
          setTerrainReady(false);
          viewer.terrainProvider = new EllipsoidTerrainProvider();
          viewer.scene.requestRender();
          return;
        }

        if (cachedIonTerrainRef.current?.token === token && cachedIonTerrainRef.current.provider) {
          viewer.terrainProvider = cachedIonTerrainRef.current.provider as never;
          setTerrainReady(true);
          viewer.scene.requestRender();
          return;
        }

        setTerrainReady(false);
        const terrain = await createWorldTerrainAsync();
        if (cancelled) return;
        cachedIonTerrainRef.current = { token, provider: terrain as unknown };
        viewer.terrainProvider = terrain;
        setTerrainReady(true);
        viewer.scene.requestRender();
        return;
      }

      if (terrainProviderMode === 'selfHosted') {
        const terrainUrl = mapConfig?.selfHosted?.terrainUrl;
        if (!terrainUrl) {
          console.warn('[Digital Earth] map.terrainProvider=selfHosted requires map.selfHosted.terrainUrl');
          setTerrainNotice('未配置自建地形地址，已回退到无地形模式。');
          setTerrainReady(false);
          viewer.terrainProvider = new EllipsoidTerrainProvider();
          viewer.scene.requestRender();
          return;
        }

        if (
          cachedSelfHostedTerrainRef.current?.terrainUrl === terrainUrl &&
          cachedSelfHostedTerrainRef.current.provider
        ) {
          viewer.terrainProvider = cachedSelfHostedTerrainRef.current.provider as never;
          setTerrainReady(true);
          viewer.scene.requestRender();
          return;
        }

        setTerrainReady(false);
        const terrain = await CesiumTerrainProvider.fromUrl(terrainUrl);
        if (cancelled) return;
        cachedSelfHostedTerrainRef.current = { terrainUrl, provider: terrain as unknown };
        viewer.terrainProvider = terrain;
        setTerrainReady(true);
        viewer.scene.requestRender();
      }
    };

    void applyTerrainProvider().catch((error: unknown) => {
      if (cancelled) return;
      console.warn('[Digital Earth] failed to apply terrain provider', error);
      setTerrainNotice('地形加载失败，已回退到无地形模式。');
      setTerrainReady(false);
      viewer.terrainProvider = new EllipsoidTerrainProvider();
      viewer.scene.requestRender();
    });

    return () => {
      cancelled = true;
    };
  }, [mapConfig, viewModeRoute.viewModeId, viewer]);

  useEffect(() => {
    const NO_TERRAIN_NOTICE = '当前环境未启用 DEM 地形，Local 视角精度受限。';

    if (!mapConfigLoaded) return;

    const shouldShow =
      viewModeRoute.viewModeId === 'local' &&
      (mapConfig?.terrainProvider === undefined || mapConfig.terrainProvider === 'none');

    setTerrainNotice((current) => {
      const isGeneric = current === NO_TERRAIN_NOTICE;

      if (shouldShow) {
        return current ?? NO_TERRAIN_NOTICE;
      }

      return isGeneric ? null : current;
    });
  }, [mapConfig?.terrainProvider, mapConfigLoaded, viewModeRoute.viewModeId]);

  useEffect(() => {
    if (!viewer) return;
    if (viewModeRoute.viewModeId !== 'local') {
      localTerrainSampleKeyRef.current = null;
      return;
    }
    if (!terrainReady) {
      localTerrainSampleKeyRef.current = null;
      return;
    }

    const { lon, lat } = viewModeRoute;
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;

    const key = `${lon}:${lat}`;
    if (localTerrainSampleKeyRef.current === key) return;
    localTerrainSampleKeyRef.current = key;

    let cancelled = false;

    void (async () => {
      try {
        const sampledHeight = await requestLocalGroundHeightMeters({ lon, lat });
        if (cancelled) return;
        if (typeof sampledHeight !== 'number' || !Number.isFinite(sampledHeight)) return;

        const currentRoute = useViewModeStore.getState().route;
        if (currentRoute.viewModeId !== 'local') return;
        if (!Object.is(currentRoute.lon, lon) || !Object.is(currentRoute.lat, lat)) return;

        const currentHeight = currentRoute.heightMeters;
        const heightChanged =
          typeof currentHeight !== 'number' ||
          !Number.isFinite(currentHeight) ||
          Math.abs(currentHeight - sampledHeight) > 0.5;
        if (!heightChanged) return;

        replaceRoute({ viewModeId: 'local', lon, lat, heightMeters: sampledHeight });
      } catch (error: unknown) {
        console.warn('[Digital Earth] failed to sample terrain height', error);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [replaceRoute, requestLocalGroundHeightMeters, terrainReady, viewModeRoute, viewer]);

  useEffect(() => {
    if (!viewer) return;

    const duration = didApplySceneModeRef.current ? 0.8 : 0;
    didApplySceneModeRef.current = true;

    return switchViewerSceneMode(viewer, sceneModeId, { duration });
  }, [sceneModeId, viewer]);

  useEffect(() => {
    if (!viewer) return;

    const existing = temperatureLayersRef.current;
    return () => {
      for (const layer of existing.values()) {
        layer.destroy();
      }
      existing.clear();
    };
  }, [viewer]);

  useEffect(() => {
    if (!viewer) return;

    const existing = cloudLayersRef.current;
    return () => {
      for (const layer of existing.values()) {
        layer.destroy();
      }
      existing.clear();
    };
  }, [viewer]);

  useEffect(() => {
    if (!viewer) return;

    const existing = precipitationLayersRef.current;
    return () => {
      for (const layer of existing.values()) {
        layer.destroy();
      }
      existing.clear();
    };
  }, [viewer]);

  useEffect(() => {
    if (!viewer) return;

    const particles = new PrecipitationParticles(viewer);
    precipitationParticlesRef.current = particles;

    return () => {
      particles.destroy();
      precipitationParticlesRef.current = null;
    };
  }, [viewer]);

  useEffect(() => {
    if (!viewer) return;

    const cache = windVectorsCacheRef.current;
    windAbortRef.current?.abort();
    windAbortRef.current = null;
    windVectorsRef.current = [];
    windViewKeyRef.current = null;
    windVectorsKeyRef.current = null;
    windStyleKeyRef.current = null;
    cache.clear();

    const windArrows = new WindArrows(viewer, {
      maxArrows: WIND_ARROWS_MAX_COUNT,
    });
    windArrowsRef.current = windArrows;

    return () => {
      windAbortRef.current?.abort();
      windAbortRef.current = null;
      windVectorsRef.current = [];
      windViewKeyRef.current = null;
      windVectorsKeyRef.current = null;
      windStyleKeyRef.current = null;
      cache.clear();
      windArrows.destroy();
      windArrowsRef.current = null;
    };
  }, [viewer]);

  const precipitationLayerConfig = useMemo(() => {
    const visible = layers.find((layer) => layer.type === 'precipitation' && layer.visible);
    return visible ?? layers.find((layer) => layer.type === 'precipitation') ?? null;
  }, [layers]);

  const snowDepthLayerConfig = useMemo(() => {
    const visible = layers.find((layer) => layer.type === 'snow-depth' && layer.visible);
    return visible ?? layers.find((layer) => layer.type === 'snow-depth') ?? null;
  }, [layers]);

  const windLayerConfig = useMemo(() => {
    const visible = layers.find((layer) => layer.type === 'wind' && layer.visible);
    return visible ?? layers.find((layer) => layer.type === 'wind') ?? null;
  }, [layers]);

  const temperatureLayerConfig = useMemo(() => {
    const visible = layers.find((layer) => layer.type === 'temperature' && layer.visible);
    return visible ?? layers.find((layer) => layer.type === 'temperature') ?? null;
  }, [layers]);

  const cloudLayerConfig = useMemo(() => {
    const visibleTcc = layers.find(
      (layer) => layer.type === 'cloud' && layer.visible && isCloudCoverVariable(layer.variable),
    );
    if (visibleTcc) return visibleTcc;
    const anyVisible = layers.find((layer) => layer.type === 'cloud' && layer.visible);
    if (anyVisible) return anyVisible;
    const anyTcc = layers.find((layer) => layer.type === 'cloud' && isCloudCoverVariable(layer.variable));
    return anyTcc ?? layers.find((layer) => layer.type === 'cloud') ?? null;
  }, [layers]);

  const isEventAnalyticsModeActive = viewModeRoute.viewModeId === 'event' && eventLayersEnabled;
  const isHistoricalAnalyticsActive = isEventAnalyticsModeActive && eventLayersMode === 'history';
  const isBiasAnalyticsActive = isEventAnalyticsModeActive && eventLayersMode === 'difference';

  const loadHistoricalAnalyticsLayer = useCallback(
    async ({
      apiBaseUrl,
      signal,
    }: {
      apiBaseUrl: string;
      signal: AbortSignal;
    }): Promise<AnalyticsTileLayerParams | null> => {
      const desiredWindowEnd = eventMonitoringTimeKey
        ? alignToMostRecentHourTimeKey(eventMonitoringTimeKey)
        : '';
      const eventType = canonicalizeEventType(eventTitle ?? '');
      const statsFilters = historicalStatisticsFiltersForEvent(eventType);

      const response = await fetchHistoricalStatistics({
        apiBaseUrl,
        source: statsFilters.source,
        variable: statsFilters.variable ?? undefined,
        window_kind: statsFilters.window_kind,
        fmt: 'png',
        limit: EVENT_ANALYTICS_LIST_LIMIT,
        signal,
      });
      if (signal.aborted) return null;

      const candidates =
        eventType === 'snow'
          ? response.items.filter((item) => item.variable.toLowerCase().includes('snow'))
          : response.items;

      const matchWindowEnd =
        desiredWindowEnd.trim() === ''
          ? null
          : candidates.find((item) => item.window_key.startsWith(desiredWindowEnd.trim()));

      const selected = matchWindowEnd ?? candidates[0] ?? null;
      const template =
        selected?.tiles.mean?.template ??
        selected?.tiles.sum?.template ??
        Object.values(selected?.tiles ?? {})[0]?.template ??
        null;

      if (!selected || !template) return null;

      const urlTemplate = new URL(template, apiBaseUrl).toString();
      const frameKey = `historical:${selected.source}:${selected.variable}:${selected.window_key}:${selected.version}`;
      const rectangle = eventMonitoringRectangle ?? undefined;
      const [minimumLevel, maximumLevel] = rectangle ? [8, 10] : [0, 6];
      const opacity = snowDepthLayerConfig?.opacity ?? 0.75;

      return {
        id: 'event-historical',
        urlTemplate,
        frameKey,
        opacity,
        visible: true,
        zIndex: 60,
        rectangle,
        minimumLevel,
        maximumLevel,
        credit: 'Historical statistics tiles',
      };
    },
    [eventMonitoringRectangle, eventMonitoringTimeKey, eventTitle, snowDepthLayerConfig?.opacity],
  );

  useEventAnalyticsTileLayer({
    viewer,
    apiBaseUrl,
    active: isHistoricalAnalyticsActive,
    layerRef: eventHistoricalLayerRef,
    setStatus: setEventHistoricalLayerStatus,
    load: loadHistoricalAnalyticsLayer,
    logLabel: 'historical statistics layer',
  });

  const loadBiasAnalyticsLayer = useCallback(
    async ({
      apiBaseUrl,
      signal,
    }: {
      apiBaseUrl: string;
      signal: AbortSignal;
    }): Promise<AnalyticsTileLayerParams | null> => {
      const desiredTimeKey = eventMonitoringTimeKey
        ? alignToMostRecentHourTimeKey(eventMonitoringTimeKey)
        : '';
      const eventType = canonicalizeEventType(eventTitle ?? '');

      const response = await fetchBiasTileSets({
        apiBaseUrl,
        fmt: 'png',
        limit: EVENT_ANALYTICS_LIST_LIMIT,
        signal,
      });
      if (signal.aborted) return null;

      const items = response.items;
      if (items.length === 0) return null;

      const availableLayers = Array.from(new Set(items.map((item) => item.layer)));
      const selectedLayer = pickBiasLayerForEvent(eventType, availableLayers) ?? items[0]!.layer;
      const layerItems = items.filter((item) => item.layer === selectedLayer);

      const byTime = desiredTimeKey
        ? layerItems.filter((item) => item.time_key === desiredTimeKey)
        : layerItems;
      const candidates = byTime.length > 0 ? byTime : layerItems;
      const selected =
        candidates.find((item) => item.level_key.trim().toLowerCase() === 'sfc') ??
        candidates[0] ??
        null;

      const template = selected?.tile.template ?? '';
      if (!selected || !template) return null;

      const urlTemplate = new URL(template, apiBaseUrl).toString();
      const frameKey = `bias:${selected.layer}:${selected.time_key}:${selected.level_key}`;
      const opacity = snowDepthLayerConfig?.opacity ?? 0.75;

      return {
        id: 'event-bias',
        urlTemplate,
        frameKey,
        opacity,
        visible: true,
        zIndex: 60,
        rectangle: eventMonitoringRectangle ?? undefined,
        minimumLevel: selected.min_zoom,
        maximumLevel: selected.max_zoom,
        credit: 'Bias tiles',
      };
    },
    [eventMonitoringRectangle, eventMonitoringTimeKey, eventTitle, snowDepthLayerConfig?.opacity],
  );

  useEventAnalyticsTileLayer({
    viewer,
    apiBaseUrl,
    active: isBiasAnalyticsActive,
    layerRef: eventBiasLayerRef,
    setStatus: setEventBiasLayerStatus,
    load: loadBiasAnalyticsLayer,
    logLabel: 'bias layer',
  });

  useEffect(() => {
    if (!apiBaseUrl) return;
    if (!precipitationLayerConfig) {
      weatherSamplerRef.current = null;
      return;
    }

    const precipitationTemplate = buildPrecipitationTileUrlTemplate({
      apiBaseUrl,
      timeKey,
      threshold: precipitationLayerConfig.threshold,
    });

    const temperatureTemplate = buildEcmwfTemperatureTileUrlTemplate({
      apiBaseUrl,
      timeKey,
      level: 'sfc',
    });

    weatherSamplerRef.current = createWeatherSampler({
      zoom: WEATHER_SAMPLE_ZOOM,
      precipitation: { urlTemplate: precipitationTemplate },
      temperature: { urlTemplate: temperatureTemplate },
    });
  }, [apiBaseUrl, precipitationLayerConfig, temperatureLayerConfig, timeKey]);

  useEffect(() => {
    if (!apiBaseUrl) {
      cloudSamplerRef.current = null;
      return;
    }
    if (!cloudLayerConfig) {
      cloudSamplerRef.current = null;
      return;
    }

    const cloudTemplate = buildCloudTileUrlTemplate({
      apiBaseUrl,
      timeKey: cloudTimeKey,
      variable: cloudLayerConfig.variable,
    });

    cloudSamplerRef.current = createCloudSampler({
      zoom: WEATHER_SAMPLE_ZOOM,
      cloud: { urlTemplate: cloudTemplate },
    });
  }, [apiBaseUrl, cloudLayerConfig, cloudTimeKey]);

  useEffect(() => {
    if (!viewer) return;

    const handler = viewer.screenSpaceEventHandler as unknown as {
      setInputAction?: (
        cb: (movement: { position?: unknown }) => void,
        type: unknown,
        modifier?: unknown,
      ) => void;
      removeInputAction?: (type: unknown, modifier?: unknown) => void;
    };

    if (!handler?.setInputAction) return;

    const pickLocation = (
      position: unknown,
    ): { lon: number; lat: number; heightMeters: number | undefined } | null => {
      const cartesian =
        (viewer.scene as unknown as { pickPosition?: (pos: unknown) => unknown }).pickPosition?.(
          position,
        ) ??
        (viewer.camera as unknown as {
          pickEllipsoid?: (pos: unknown, ellipsoid?: unknown) => unknown;
        }).pickEllipsoid?.(
          position,
          (viewer.scene as unknown as { globe?: { ellipsoid?: unknown } }).globe?.ellipsoid,
        );

      if (!cartesian) return null;

      const cartographic = Cartographic.fromCartesian(cartesian as never) as Cartographic & {
        height?: number;
      };
      const lon = CesiumMath.toDegrees(cartographic.longitude);
      const lat = CesiumMath.toDegrees(cartographic.latitude);
      const heightMeters = cartographic.height;

      if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
      return {
        lon,
        lat,
        heightMeters:
          typeof heightMeters === 'number' && Number.isFinite(heightMeters)
            ? heightMeters
            : undefined,
      };
    };

    const onEnterLocal = (movement: { position?: unknown }) => {
      const position = movement.position;
      if (!position) return;

      const picked = pickLocation(position);
      if (!picked) return;

      // Cancel any ongoing sampling and close the card to avoid conflict with double-click
      samplingAbortRef.current?.abort();
      closeSamplingCard();

      enterLocal({
        lon: picked.lon,
        lat: picked.lat,
        heightMeters: picked.heightMeters ?? null,
      });
    };

	    const onClick = (movement: { position?: unknown }) => {
	      const position = movement.position;
	      if (!position) return;

	      const normalizeScreenPosition = (value: unknown): { x: number; y: number } | null => {
	        if (!value || typeof value !== 'object') return null;
	        const x = (value as { x?: unknown }).x;
	        const y = (value as { y?: unknown }).y;
	        if (typeof x !== 'number' || !Number.isFinite(x)) return null;
	        if (typeof y !== 'number' || !Number.isFinite(y)) return null;
	        return { x, y };
	      };

	      const openRiskPopup = (poiId: number) => {
	        if (!Number.isFinite(poiId)) return;
	        const poi = riskPoisByIdRef.current.get(poiId);
	        if (!poi) return;

	        samplingAbortRef.current?.abort();
	        closeSamplingCard();

	        const existing = riskEvalByIdRef.current.get(poiId) ?? null;
	        setRiskPopup({
	          poi,
	          evaluation: existing,
	          status: existing ? 'loaded' : 'loading',
	          errorMessage: null,
	        });

	        if (!existing && apiBaseUrl && eventMonitoringTimeKey) {
	          const route = useViewModeStore.getState().route;
	          if (route.viewModeId !== 'event') return;

	          riskPopupAbortRef.current?.abort();
	          const controller = new AbortController();
	          riskPopupAbortRef.current = controller;

	          void (async () => {
	            try {
	              const evaluation = await evaluateRisk({
	                apiBaseUrl,
	                productId: route.productId,
	                validTime: eventMonitoringTimeKey,
	                poiIds: [poiId],
	                signal: controller.signal,
	              });
	              if (controller.signal.aborted) return;
	              const result = evaluation.results.find((item) => item.poi_id === poiId) ?? null;
	              if (result) riskEvalByIdRef.current.set(poiId, result);
	              setRiskPopup((prev) => {
	                if (!prev || prev.poi.id !== poiId) return prev;
	                return { ...prev, evaluation: result, status: 'loaded', errorMessage: null };
	              });
	            } catch (error) {
	              if (controller.signal.aborted) return;
	              console.warn('[Digital Earth] failed to evaluate risk poi', error);
	              setRiskPopup((prev) => {
	                if (!prev || prev.poi.id !== poiId) return prev;
	                return { ...prev, status: 'error', errorMessage: '风险详情加载失败' };
	              });
	            } finally {
	              if (riskPopupAbortRef.current === controller) riskPopupAbortRef.current = null;
	            }
	          })();
	        }
	      };

	      const extractPickedId = (picked: unknown): string | null => {
	        if (!picked || typeof picked !== 'object') return null;
	        const raw = (picked as { id?: unknown }).id;
	        if (typeof raw === 'string') return raw;
	        if (raw && typeof raw === 'object') {
	          const nested = (raw as { id?: unknown }).id;
	          if (typeof nested === 'string') return nested;
	        }
	        return null;
	      };

	      const scene = viewer.scene as unknown as {
	        pick?: (pos: unknown) => unknown;
	        drillPick?: (pos: unknown, limit?: number) => unknown[];
	      };

	      const pickedObjects =
	        typeof scene.drillPick === 'function'
	          ? scene.drillPick(position, 10)
	          : [scene.pick?.(position)];

	      const pickedIds = pickedObjects
	        .map(extractPickedId)
	        .filter((id): id is string => Boolean(id));

	      const riskPoiMatch = pickedIds
	        .map((id) => /^risk-poi:(\d+)$/.exec(id))
	        .find((match): match is RegExpExecArray => Boolean(match));
	      if (riskPoiMatch) {
	        const poiId = Number(riskPoiMatch[1]);
	        openRiskPopup(poiId);
	        return;
	      }

	      const route = useViewModeStore.getState().route;
	      if (route.viewModeId === 'event') {
	        const screenPos = normalizeScreenPosition(position);
	        const dataSource = riskDataSourceRef.current as unknown as {
	          entities?: { getById?: (id: string) => unknown };
	        } | null;

	        if (screenPos && dataSource?.entities?.getById) {
	          let nearestPoiId: number | null = null;
	          let nearestDist2 = Number.POSITIVE_INFINITY;

	          for (const poiId of riskPoisByIdRef.current.keys()) {
	            const entity = dataSource.entities.getById(`risk-poi:${poiId}`) as
	              | { position?: { getValue?: (time: unknown) => unknown } }
	              | undefined;
	            const worldPosition = entity?.position?.getValue?.(viewer.clock.currentTime);
	            if (!worldPosition) continue;

	            const coords = SceneTransforms.worldToWindowCoordinates(
	              viewer.scene,
	              worldPosition as Cartesian3,
	            );
	            const x = coords?.x;
	            const y = coords?.y;
	            if (typeof x !== 'number' || !Number.isFinite(x)) continue;
	            if (typeof y !== 'number' || !Number.isFinite(y)) continue;

	            const dx = x - screenPos.x;
	            const dy = y - screenPos.y;
	            const dist2 = dx * dx + dy * dy;
	            if (dist2 < nearestDist2) {
	              nearestDist2 = dist2;
	              nearestPoiId = poiId;
	            }
	          }

	          const thresholdPx = 20;
	          if (nearestPoiId != null && nearestDist2 <= thresholdPx * thresholdPx) {
	            openRiskPopup(nearestPoiId);
	            return;
	          }
	        }
	      }

	      const picked = pickLocation(position);

	      if (!picked) {
	        openSamplingCard({ lon: Number.NaN, lat: Number.NaN });
        setSamplingError('无法获取点击位置');
        return;
      }

      const { lon, lat } = picked;

      samplingAbortRef.current?.abort();
      const controller = new AbortController();
      samplingAbortRef.current = controller;

      openSamplingCard({ lon, lat });

      const sampler = weatherSamplerRef.current;
      const cloudSampler = cloudSamplerRef.current;
      const windVectors = windVectorsRef.current;

      void (async () => {
        try {
          const [weather, cloud] = await Promise.all([
            sampler?.sample({ lon, lat, signal: controller.signal }) ??
              Promise.resolve({
                precipitationMm: null,
                precipitationIntensity: 0,
                precipitationKind: 'none' as const,
                temperatureC: null,
              }),
            cloudSampler?.sample({ lon, lat, signal: controller.signal }) ??
              Promise.resolve({ cloudCoverFraction: null }),
          ]);

          if (controller.signal.aborted) return;

          const wind = sampleWindVectorAt(windVectors, { lon, lat });
          setSamplingData({
            temperatureC: weather.temperatureC,
            precipitationMm: weather.precipitationMm,
            windSpeedMps: wind?.speedMps ?? null,
            windDirectionDeg: wind?.directionDeg ?? null,
            cloudCoverPercent:
              cloud.cloudCoverFraction == null
                ? null
                : Math.max(0, Math.min(100, cloud.cloudCoverFraction * 100)),
          });
        } catch {
          if (controller.signal.aborted) return;
          setSamplingError('取样失败');
        }
      })();
    };

    handler.setInputAction(onClick, ScreenSpaceEventType.LEFT_CLICK);
    handler.setInputAction(onEnterLocal, ScreenSpaceEventType.LEFT_CLICK, KeyboardEventModifier.CTRL);
    handler.setInputAction(onEnterLocal, ScreenSpaceEventType.LEFT_DOUBLE_CLICK);

    return () => {
      handler.removeInputAction?.(ScreenSpaceEventType.LEFT_CLICK);
      handler.removeInputAction?.(ScreenSpaceEventType.LEFT_CLICK, KeyboardEventModifier.CTRL);
      handler.removeInputAction?.(ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
    };
  }, [
    apiBaseUrl,
    closeSamplingCard,
    enterLocal,
    eventMonitoringTimeKey,
    openSamplingCard,
    setSamplingData,
    setSamplingError,
    viewer,
  ]);

  useEffect(() => {
    if (!viewer) return;
    if (viewModeRoute.viewModeId !== 'local') {
      localEntryKeyRef.current = null;
      localHumanEntryKeyRef.current = null;
      localHumanLandingAbortRef.current?.abort();
      localHumanLandingAbortRef.current = null;
      return;
    }

    const surfaceHeightMeters =
      typeof viewModeRoute.heightMeters === 'number' && Number.isFinite(viewModeRoute.heightMeters)
        ? viewModeRoute.heightMeters
        : 0;

    const key = `${sceneModeId}:${viewModeRoute.lon}:${viewModeRoute.lat}:${surfaceHeightMeters}`;
    if (localEntryKeyRef.current === key) return;
    localEntryKeyRef.current = key;

    const pendingRestore = pendingLocalCameraRestoreRef.current;
    if (pendingRestore) {
      pendingLocalCameraRestoreRef.current = null;

      const destination = Cartesian3.fromDegrees(
        pendingRestore.lon,
        pendingRestore.lat,
        pendingRestore.heightMeters,
      );

      const pitch =
        cameraPerspectiveId === 'free'
          ? pendingRestore.pitch
          : cameraPitchForPerspective(cameraPerspectiveId) ?? LOCAL_FREE_PITCH;
      const roll = cameraPerspectiveId === 'free' ? pendingRestore.roll : 0;

      viewer.camera.flyTo({
        destination,
        orientation: {
          heading: pendingRestore.heading,
          pitch,
          roll,
        },
        duration: 1.2,
      });
      appliedCameraPerspectiveRef.current = cameraPerspectiveId;
      return;
    }

    if (cameraPerspectiveId === 'human' && sceneModeId !== '2d') {
      appliedCameraPerspectiveRef.current = cameraPerspectiveId;

      localHumanLandingAbortRef.current?.abort();
      const controller = new AbortController();
      localHumanLandingAbortRef.current = controller;

      const target = { lon: viewModeRoute.lon, lat: viewModeRoute.lat };
      const lonLatKey = `${sceneModeId}:${target.lon}:${target.lat}`;
      const isNewTarget = localHumanEntryKeyRef.current !== lonLatKey;
      localHumanEntryKeyRef.current = lonLatKey;

      const heading = viewer.camera.heading;
      const pitch = cameraPitchForPerspective(cameraPerspectiveId) ?? LOCAL_FORWARD_PITCH;

      if (!isNewTarget) {
        const destination = Cartesian3.fromDegrees(
          target.lon,
          target.lat,
          surfaceHeightMeters + HUMAN_EYE_HEIGHT_METERS,
        );

        viewer.camera.flyTo({
          destination,
          orientation: { heading, pitch, roll: 0 },
          duration: 0.8,
        });
        return () => {
          controller.abort();
          if (localHumanLandingAbortRef.current === controller) {
            localHumanLandingAbortRef.current = null;
          }
        };
      }

      const safeDestination = Cartesian3.fromDegrees(
        target.lon,
        target.lat,
        surfaceHeightMeters + HUMAN_SAFE_HEIGHT_OFFSET_METERS,
      );

      void flyCameraToAsync(viewer.camera, {
        destination: safeDestination,
        orientation: { heading, pitch, roll: 0 },
        duration: 1.4,
      }).then(async () => {
        if (controller.signal.aborted) return;

        const currentRoute = useViewModeStore.getState().route;
        if (currentRoute.viewModeId !== 'local') return;
        if (!Object.is(currentRoute.lon, target.lon) || !Object.is(currentRoute.lat, target.lat)) return;
        if (useCameraPerspectiveStore.getState().cameraPerspectiveId !== 'human') return;

        const sampledHeight = await requestLocalGroundHeightMeters(target);
        if (controller.signal.aborted) return;

        const groundHeightMeters = sampledHeight ?? surfaceHeightMeters;
        if (sampledHeight != null) {
          const currentHeight = currentRoute.heightMeters;
          const heightChanged =
            typeof currentHeight !== 'number' ||
            !Number.isFinite(currentHeight) ||
            Math.abs(currentHeight - sampledHeight) > 0.5;
          if (heightChanged) {
            localEntryKeyRef.current = `${sceneModeId}:${target.lon}:${target.lat}:${sampledHeight}`;
            replaceRoute({
              viewModeId: 'local',
              lon: target.lon,
              lat: target.lat,
              heightMeters: sampledHeight,
            });
          }
        }

        const destination = Cartesian3.fromDegrees(
          target.lon,
          target.lat,
          groundHeightMeters + HUMAN_EYE_HEIGHT_METERS,
        );

        viewer.camera.flyTo({
          destination,
          orientation: { heading, pitch, roll: 0 },
          duration: 1.1,
        });
      });

      return () => {
        controller.abort();
        if (localHumanLandingAbortRef.current === controller) {
          localHumanLandingAbortRef.current = null;
        }
      };
    }

    const offsetMeters = sceneModeId === '2d' ? 5000 : cameraPerspectiveId === 'free' ? 3000 : 50;
    const destination = Cartesian3.fromDegrees(
      viewModeRoute.lon,
      viewModeRoute.lat,
      surfaceHeightMeters + offsetMeters,
    );

    viewer.camera.flyTo({
      destination,
      orientation: {
        heading: viewer.camera.heading,
        pitch: cameraPitchForPerspective(cameraPerspectiveId) ?? LOCAL_FREE_PITCH,
        roll: 0,
      },
      duration: 2.5,
    });
    appliedCameraPerspectiveRef.current = cameraPerspectiveId;
  }, [cameraPerspectiveId, replaceRoute, requestLocalGroundHeightMeters, sceneModeId, viewModeRoute, viewer]);

  useEffect(() => {
    if (!viewer) return;

    if (viewModeRoute.viewModeId !== 'event') {
      eventEntryKeyRef.current = null;
      eventAutoLayerProductIdRef.current = null;
      eventAbortRef.current?.abort();
      eventAbortRef.current = null;

      if (eventEntitiesRef.current.length > 0) {
        for (const entity of eventEntitiesRef.current) {
          viewer.entities.remove(entity);
        }
        eventEntitiesRef.current = [];
        viewer.scene.requestRender();
      }

      setEventMonitoringTimeKey(null);
      setEventMonitoringRectangle(null);
      setEventTitle(null);
      return;
    }

    if (!apiBaseUrl) return;

    const productId = viewModeRoute.productId.trim();
    if (!productId) return;

    if (eventAutoLayerProductIdRef.current !== productId) {
      eventAutoLayerProductIdRef.current = productId;
      eventAutoLayerTypeRef.current = null;
      eventAutoLayerAppliedRef.current = false;
    }

    const key = `${sceneModeId}:${apiBaseUrl}:${productId}`;
    if (eventEntryKeyRef.current === key) return;
    eventEntryKeyRef.current = key;

    eventAbortRef.current?.abort();
    const controller = new AbortController();
    eventAbortRef.current = controller;

    if (eventEntitiesRef.current.length > 0) {
      for (const entity of eventEntitiesRef.current) {
        viewer.entities.remove(entity);
      }
      eventEntitiesRef.current = [];
      viewer.scene.requestRender();
    }

    void (async () => {
      try {
        const product = await getProductDetail({
          apiBaseUrl,
          productId,
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        if (eventEntryKeyRef.current !== key) return;

        eventAutoLayerTypeRef.current = product.title;
        setEventTitle(product.title);
        maybeApplyEventAutoLayerTemplate();

        const hazards = product.hazards;
        const destinationBBox = bboxUnion(hazards.map((hazard) => hazard.bbox));

        setEventMonitoringTimeKey(product.valid_from);
        if (destinationBBox) {
          setEventMonitoringRectangle({
            west: destinationBBox.min_x,
            south: destinationBBox.min_y,
            east: destinationBBox.max_x,
            north: destinationBBox.max_y,
          });
        } else {
          setEventMonitoringRectangle(null);
        }

        const nextEntities: Entity[] = [];

        for (const hazard of hazards) {
          const { fill, outline } = materialForSeverity(hazard.severity);
          const hierarchies = polygonHierarchiesForHazard(hazard);
          for (const [index, hierarchy] of hierarchies.entries()) {
            const polygon = new PolygonGraphics({
              hierarchy,
              material: fill,
              outline: true,
              outlineColor: outline,
              outlineWidth: 2,
            });
            const entity = new Entity({
              id: `event:${productId}:${hazard.id}:${index}`,
              polygon,
            });
            viewer.entities.add(entity);
            nextEntities.push(entity);
          }
        }

        eventEntitiesRef.current = nextEntities;

        if (destinationBBox) {
          const rectangle = Rectangle.fromDegrees(
            destinationBBox.min_x,
            destinationBBox.min_y,
            destinationBBox.max_x,
            destinationBBox.max_y,
          );
          viewer.camera.flyTo({ destination: rectangle, duration: 1.8 });
        }

        viewer.scene.requestRender();
      } catch (error) {
        if (controller.signal.aborted) return;
        if (eventEntryKeyRef.current !== key) return;
        console.warn('[Digital Earth] failed to plot event polygon', error);
        setEventMonitoringTimeKey(null);
        setEventMonitoringRectangle(null);
        viewer.scene.requestRender();
      } finally {
        if (eventAbortRef.current === controller) eventAbortRef.current = null;
      }
    })();

    return () => controller.abort();
  }, [apiBaseUrl, maybeApplyEventAutoLayerTemplate, sceneModeId, viewModeRoute, viewer]);

  useEffect(() => {
    if (!viewer) return;

    if (viewModeRoute.viewModeId !== 'event') {
      riskEntryKeyRef.current = null;
      riskAbortRef.current?.abort();
      riskAbortRef.current = null;
      riskPopupAbortRef.current?.abort();
      riskPopupAbortRef.current = null;
      riskPoisByIdRef.current.clear();
      riskEvalByIdRef.current.clear();
      setRiskPopup(null);
      setDisasterDemoOpen(false);

      const dataSource = riskDataSourceRef.current;
      if (dataSource) {
        viewer.dataSources.remove(dataSource, true);
        riskDataSourceRef.current = null;
        riskClusterTeardownRef.current?.();
        riskClusterTeardownRef.current = null;
        viewer.scene.requestRender();
      }
      return;
    }

    if (!apiBaseUrl) return;

    const productId = viewModeRoute.productId.trim();
    if (!productId) return;
    if (!eventMonitoringRectangle) return;
    if (!eventMonitoringTimeKey) return;

    const bbox: BBox = {
      min_x: eventMonitoringRectangle.west,
      min_y: eventMonitoringRectangle.south,
      max_x: eventMonitoringRectangle.east,
      max_y: eventMonitoringRectangle.north,
    };

    const key = `${apiBaseUrl}:${productId}:${eventMonitoringTimeKey}:${bbox.min_x},${bbox.min_y},${bbox.max_x},${bbox.max_y}`;
    if (riskEntryKeyRef.current === key) return;
    riskEntryKeyRef.current = key;

    riskAbortRef.current?.abort();
    const controller = new AbortController();
    riskAbortRef.current = controller;

    let dataSource = riskDataSourceRef.current;
    if (!dataSource) {
      dataSource = new CustomDataSource('risk-pois');
      riskDataSourceRef.current = dataSource;
      void viewer.dataSources.add(dataSource);
      riskClusterTeardownRef.current?.();
      riskClusterTeardownRef.current = setupRiskPoiClustering(viewer, dataSource);
    } else {
      dataSource.entities.removeAll();
      viewer.scene.requestRender();
    }

	    riskPoisByIdRef.current.clear();
	    riskEvalByIdRef.current.clear();

	    void (async () => {
	      try {
	        const pois = await getRiskPois({
	          apiBaseUrl,
	          bbox,
	          signal: controller.signal,
	        });
	        if (controller.signal.aborted) return;
	        if (riskEntryKeyRef.current !== key) return;

	        const poiById = new Map<number, RiskPOI>();
	        for (const poi of pois) poiById.set(poi.id, poi);
	        riskPoisByIdRef.current = poiById;

	        const plotPois = (evalMap: Map<number, POIRiskResult>) => {
	          dataSource.entities.removeAll();
	          for (const poi of pois) {
	            const result = evalMap.get(poi.id);
	            const level = result?.level ?? poi.risk_level;
	            const color = colorForRiskLevel(level);
	            dataSource.entities.add(
	              new Entity({
	                id: `risk-poi:${poi.id}`,
	                position: Cartesian3.fromDegrees(poi.lon, poi.lat, poi.alt ?? 0),
	                point: {
	                  pixelSize: 12,
	                  color: color.withAlpha(0.85),
	                  outlineColor: Color.WHITE.withAlpha(0.9),
	                  outlineWidth: 2,
	                  disableDepthTestDistance: Number.POSITIVE_INFINITY,
	                },
	                label: {
	                  text: formatRiskLevel(level),
	                  font: 'bold 14px sans-serif',
	                  fillColor: Color.WHITE,
	                  showBackground: true,
	                  backgroundColor: color.withAlpha(0.85),
	                  disableDepthTestDistance: Number.POSITIVE_INFINITY,
	                },
	              }),
	            );
	          }
	        };

	        // Render POIs immediately using the base `risk_level` values so a risk evaluation
	        // failure does not result in an empty layer.
	        plotPois(riskEvalByIdRef.current);

	        viewer.scene.requestRender();

	        try {
	          if (pois.length === 0) return;
	          const evaluation = await evaluateRisk({
	            apiBaseUrl,
	            productId,
	            validTime: eventMonitoringTimeKey,
	            bbox: [bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y],
	            signal: controller.signal,
	          });

	          if (controller.signal.aborted) return;
	          if (riskEntryKeyRef.current !== key) return;

	          const nextEvalMap = new Map<number, POIRiskResult>();
	          for (const result of evaluation.results) nextEvalMap.set(result.poi_id, result);
	          riskEvalByIdRef.current = nextEvalMap;
	          plotPois(nextEvalMap);
	          viewer.scene.requestRender();
	        } catch (error) {
	          if (controller.signal.aborted) return;
	          if (riskEntryKeyRef.current !== key) return;
	          console.warn('[Digital Earth] failed to evaluate risk levels', error);
	        }
	      } catch (error) {
	        if (controller.signal.aborted) return;
	        if (riskEntryKeyRef.current !== key) return;
	        console.warn('[Digital Earth] failed to load risk POIs', error);
        riskPoisByIdRef.current.clear();
        riskEvalByIdRef.current.clear();
        dataSource.entities.removeAll();
        viewer.scene.requestRender();
      } finally {
        if (riskAbortRef.current === controller) riskAbortRef.current = null;
      }
    })();

    return () => controller.abort();
  }, [
    apiBaseUrl,
    eventMonitoringRectangle,
    eventMonitoringTimeKey,
    viewModeRoute,
    viewer,
  ]);

  useEffect(() => {
    if (!apiBaseUrl) {
      setMonitoringNotice(null);
      return;
    }
    if (!snowDepthLayerConfig?.visible) {
      setMonitoringNotice(null);
      return;
    }

    const controller = new AbortController();
    const timeKey = alignToMostRecentHourTimeKey(snowDepthTimeKey);
    const variable = normalizeSnowDepthVariable(snowDepthLayerConfig.variable);

    void probeCldasTileAvailability({
      apiBaseUrl,
      timeKey,
      variable,
      signal: controller.signal,
    }).then((result) => {
      if (controller.signal.aborted) return;
      if (result.status === 'missing') {
        setMonitoringNotice('暂无雪深监测数据');
        return;
      }
      if (result.status === 'error') {
        setMonitoringNotice('雪深监测数据加载失败');
        return;
      }
      setMonitoringNotice(null);
    });

    return () => controller.abort();
  }, [apiBaseUrl, snowDepthLayerConfig?.variable, snowDepthLayerConfig?.visible, snowDepthTimeKey]);

  useEffect(() => {
    if (!viewer) return;
    if (viewModeRoute.viewModeId !== 'layerGlobal') {
      layerGlobalEntryKeyRef.current = null;
      return;
    }

    const targetLayer =
      layers.find((layer) => layer.id === viewModeRoute.layerId) ?? null;
    const shellHeightMeters = targetLayer
      ? LAYER_GLOBAL_SHELL_HEIGHT_METERS_BY_LAYER_TYPE[targetLayer.type]
      : LAYER_GLOBAL_SHELL_HEIGHT_METERS_BY_LAYER_TYPE.cloud;

    if (targetLayer && !targetLayer.visible) {
      useLayerManagerStore.getState().setLayerVisible(targetLayer.id, true);
    }

    const key = `${sceneModeId}:${viewModeRoute.layerId}:${shellHeightMeters}:${targetLayer ? 'present' : 'missing'}`;
    if (layerGlobalEntryKeyRef.current === key) return;
    layerGlobalEntryKeyRef.current = key;

    const cartographic = viewer.camera.positionCartographic;
    const lon =
      typeof cartographic?.longitude === 'number' && Number.isFinite(cartographic.longitude)
        ? wrapLongitudeDegrees(CesiumMath.toDegrees(cartographic.longitude))
        : DEFAULT_CAMERA.longitude;
    const lat =
      typeof cartographic?.latitude === 'number' && Number.isFinite(cartographic.latitude)
        ? clampLatitudeDegrees(CesiumMath.toDegrees(cartographic.latitude))
        : DEFAULT_CAMERA.latitude;
    const currentHeightMeters =
      typeof cartographic?.height === 'number' && Number.isFinite(cartographic.height)
        ? cartographic.height
        : 0;
    const heightOffsetMeters = Math.max(shellHeightMeters * 0.5, 1000);
    const targetHeightMeters = Math.max(
      DEFAULT_CAMERA.heightMeters,
      shellHeightMeters + heightOffsetMeters,
      currentHeightMeters,
    );
    const destination = Cartesian3.fromDegrees(lon, lat, targetHeightMeters);
    viewer.camera.flyTo({
      destination,
      orientation: {
        heading: 0,
        pitch: -CesiumMath.PI_OVER_TWO,
        roll: 0,
      },
      duration: 2.0,
    });
  }, [layers, sceneModeId, viewModeRoute, viewer]);

  useEffect(() => {
    if (!viewer) return;
    if (layerGlobalShellHeightMeters == null) return;
    if (viewer.scene.mode !== SceneMode.SCENE3D) return;

    const globe = viewer.scene.globe;
    const baseTerrainProvider = viewer.terrainProvider;

    const radii = globe.ellipsoid.radii;
    const shellEllipsoid = new Ellipsoid(
      radii.x + layerGlobalShellHeightMeters,
      radii.y + layerGlobalShellHeightMeters,
      radii.z + layerGlobalShellHeightMeters,
    );

    viewer.terrainProvider = new EllipsoidTerrainProvider({ ellipsoid: shellEllipsoid });
    viewer.scene.requestRender();

    return () => {
      viewer.terrainProvider = baseTerrainProvider;
      viewer.scene.requestRender();
    };
  }, [layerGlobalShellHeightMeters, sceneModeId, viewer]);

  useEffect(() => {
    if (!viewer) return;

    const controller = viewer.scene.screenSpaceCameraController as unknown as {
      minimumZoomDistance?: number;
      enableTilt?: boolean;
      enableLook?: boolean;
      enableRotate?: boolean;
      rotateEventTypes?: unknown;
      lookEventTypes?: unknown;
    };
    const baseController = baseCameraControllerRef.current;

    if (viewModeRoute.viewModeId !== 'local') {
      const previous = appliedCameraPerspectiveRef.current;
      appliedCameraPerspectiveRef.current = null;
      localHumanLandingAbortRef.current?.abort();
      localHumanLandingAbortRef.current = null;
      if (typeof controller.minimumZoomDistance === 'number') {
        controller.minimumZoomDistance = MIN_ZOOM_DISTANCE_METERS;
      }

      if (!baseController || !previous || previous === 'free') return;
      if (typeof baseController.enableTilt === 'boolean') controller.enableTilt = baseController.enableTilt;
      if (typeof baseController.enableLook === 'boolean') controller.enableLook = baseController.enableLook;
      if (typeof baseController.enableRotate === 'boolean') controller.enableRotate = baseController.enableRotate;
      if (baseController.rotateEventTypes !== undefined) controller.rotateEventTypes = baseController.rotateEventTypes;
      if (baseController.lookEventTypes !== undefined) controller.lookEventTypes = baseController.lookEventTypes;
      viewer.scene.requestRender();
      return;
    }

    if (typeof controller.minimumZoomDistance === 'number') {
      controller.minimumZoomDistance =
        cameraPerspectiveId === 'human' ? HUMAN_MIN_ZOOM_DISTANCE_METERS : MIN_ZOOM_DISTANCE_METERS;
    }

    if (cameraPerspectiveId !== 'human') {
      localHumanLandingAbortRef.current?.abort();
      localHumanLandingAbortRef.current = null;
    }

    if (cameraPerspectiveId === 'free') {
      if (baseController) {
        if (typeof baseController.enableTilt === 'boolean') controller.enableTilt = baseController.enableTilt;
        if (typeof baseController.enableLook === 'boolean') controller.enableLook = baseController.enableLook;
        if (typeof baseController.enableRotate === 'boolean') controller.enableRotate = baseController.enableRotate;
        if (baseController.rotateEventTypes !== undefined) controller.rotateEventTypes = baseController.rotateEventTypes;
        if (baseController.lookEventTypes !== undefined) controller.lookEventTypes = baseController.lookEventTypes;
        viewer.scene.requestRender();
      }
      appliedCameraPerspectiveRef.current = cameraPerspectiveId;
      return;
    }

    if (typeof controller.enableRotate === 'boolean') {
      controller.enableRotate = false;
    }
    controller.enableLook = true;
    controller.lookEventTypes = CameraEventType.LEFT_DRAG;

    if (appliedCameraPerspectiveRef.current === cameraPerspectiveId) {
      viewer.scene.requestRender();
      return;
    }

    appliedCameraPerspectiveRef.current = cameraPerspectiveId;

    if (cameraPerspectiveId === 'human' && sceneModeId !== '2d') {
      localHumanLandingAbortRef.current?.abort();
      const controllerSignal = new AbortController();
      localHumanLandingAbortRef.current = controllerSignal;

      const target = { lon: viewModeRoute.lon, lat: viewModeRoute.lat };
      const lonLatKey = `${sceneModeId}:${target.lon}:${target.lat}`;
      const isNewTarget = localHumanEntryKeyRef.current !== lonLatKey;
      localHumanEntryKeyRef.current = lonLatKey;

      const surfaceHeightMeters =
        typeof (viewModeRoute as { heightMeters?: unknown }).heightMeters === 'number' &&
        Number.isFinite((viewModeRoute as { heightMeters?: number }).heightMeters)
          ? (viewModeRoute as { heightMeters: number }).heightMeters
          : 0;

      const heading = viewer.camera.heading;
      const pitch = cameraPitchForPerspective(cameraPerspectiveId) ?? LOCAL_FORWARD_PITCH;

      if (!isNewTarget) {
        const destination = Cartesian3.fromDegrees(
          target.lon,
          target.lat,
          surfaceHeightMeters + HUMAN_EYE_HEIGHT_METERS,
        );
        viewer.camera.flyTo({
          destination,
          orientation: { heading, pitch, roll: 0 },
          duration: 0.8,
        });
        return;
      }

      const safeDestination = Cartesian3.fromDegrees(
        target.lon,
        target.lat,
        surfaceHeightMeters + HUMAN_SAFE_HEIGHT_OFFSET_METERS,
      );

      void flyCameraToAsync(viewer.camera, {
        destination: safeDestination,
        orientation: { heading, pitch, roll: 0 },
        duration: 1.4,
      }).then(async () => {
        if (controllerSignal.signal.aborted) return;

        const currentRoute = useViewModeStore.getState().route;
        if (currentRoute.viewModeId !== 'local') return;
        if (!Object.is(currentRoute.lon, target.lon) || !Object.is(currentRoute.lat, target.lat)) return;
        if (useCameraPerspectiveStore.getState().cameraPerspectiveId !== 'human') return;

        const sampledHeight = await requestLocalGroundHeightMeters(target);
        if (controllerSignal.signal.aborted) return;

        const groundHeightMeters = sampledHeight ?? surfaceHeightMeters;
        if (sampledHeight != null) {
          const currentHeight = currentRoute.heightMeters;
          const heightChanged =
            typeof currentHeight !== 'number' ||
            !Number.isFinite(currentHeight) ||
            Math.abs(currentHeight - sampledHeight) > 0.5;
          if (heightChanged) {
            localEntryKeyRef.current = `${sceneModeId}:${target.lon}:${target.lat}:${sampledHeight}`;
            replaceRoute({
              viewModeId: 'local',
              lon: target.lon,
              lat: target.lat,
              heightMeters: sampledHeight,
            });
          }
        }

        const destination = Cartesian3.fromDegrees(
          target.lon,
          target.lat,
          groundHeightMeters + HUMAN_EYE_HEIGHT_METERS,
        );
        viewer.camera.flyTo({
          destination,
          orientation: { heading, pitch, roll: 0 },
          duration: 1.1,
        });
      });

      return;
    }

    const pitch = cameraPitchForPerspective(cameraPerspectiveId) ?? LOCAL_FREE_PITCH;
    const surfaceHeightMeters =
      typeof (viewModeRoute as { heightMeters?: unknown }).heightMeters === 'number' &&
      Number.isFinite((viewModeRoute as { heightMeters?: number }).heightMeters)
        ? (viewModeRoute as { heightMeters: number }).heightMeters
        : 0;
    const offsetMeters = sceneModeId === '2d' ? 5000 : 50;
    const destination = Cartesian3.fromDegrees(viewModeRoute.lon, viewModeRoute.lat, surfaceHeightMeters + offsetMeters);
    viewer.camera.flyTo({
      destination,
      orientation: {
        heading: viewer.camera.heading,
        pitch,
        roll: 0,
      },
      duration: 0.6,
    });
  }, [cameraPerspectiveId, replaceRoute, requestLocalGroundHeightMeters, sceneModeId, viewModeRoute, viewer]);

  useEffect(() => {
    if (!viewer) return;
    if (viewModeRoute.viewModeId !== 'local') return;

    const base = baseLocalEnvironmentRef.current;
    if (!base) return;

    const scene = viewer.scene as unknown as {
      requestRender: () => void;
      fog?: {
        enabled?: boolean;
        density?: number;
        screenSpaceErrorFactor?: number;
        minimumBrightness?: number;
      };
      skyBox?: { show?: boolean };
      skyAtmosphere?: { show?: boolean };
    };

    const camera = viewer.camera as unknown as {
      frustum?: { near?: number; far?: number; fov?: number };
      changed?: {
        addEventListener?: (handler: () => void) => void;
        removeEventListener?: (handler: () => void) => void;
      };
      moveEnd?: {
        addEventListener?: (handler: () => void) => void;
        removeEventListener?: (handler: () => void) => void;
      };
    };

    const restore = () => {
      if (scene.skyBox && typeof base.skyBoxShow === 'boolean') {
        scene.skyBox.show = base.skyBoxShow;
      }
      if (scene.skyAtmosphere && typeof base.skyAtmosphereShow === 'boolean') {
        scene.skyAtmosphere.show = base.skyAtmosphereShow;
      }
      if (scene.fog && base.fog) {
        if (typeof base.fog.enabled === 'boolean') scene.fog.enabled = base.fog.enabled;
        if (typeof base.fog.density === 'number') scene.fog.density = base.fog.density;
        if (typeof base.fog.screenSpaceErrorFactor === 'number') {
          scene.fog.screenSpaceErrorFactor = base.fog.screenSpaceErrorFactor;
        }
        if (typeof base.fog.minimumBrightness === 'number') {
          scene.fog.minimumBrightness = base.fog.minimumBrightness;
        }
      }
      if (camera.frustum && base.frustum) {
        if (typeof base.frustum.near === 'number') camera.frustum.near = base.frustum.near;
        if (typeof base.frustum.far === 'number') camera.frustum.far = base.frustum.far;
        if (typeof base.frustum.fov === 'number') camera.frustum.fov = base.frustum.fov;
      }
      scene.requestRender();
    };

    const update = () => {
      const volumetricEnabled = !lowModeEnabled;
      if (scene.skyBox) scene.skyBox.show = volumetricEnabled;
      if (scene.skyAtmosphere) scene.skyAtmosphere.show = volumetricEnabled;

      const heightMeters = getViewerCameraHeightMeters(viewer) ?? 0;

      if (camera.frustum) {
        const { near, far } =
          cameraPerspectiveId === 'human'
            ? localHumanFrustumForCameraHeight(heightMeters)
            : localFrustumForCameraHeight(heightMeters);
        camera.frustum.near = near;
        camera.frustum.far = far;
        const targetFov = CesiumMath.toRadians(75);
        const useLocalFov = cameraPerspectiveId !== 'free';
        if (useLocalFov) {
          camera.frustum.fov = targetFov;
        } else if (base.frustum && typeof base.frustum.fov === 'number') {
          camera.frustum.fov = base.frustum.fov;
        }
      }

      if (scene.fog) {
        const fogEnabled = volumetricEnabled && cameraPerspectiveId !== 'human';
        scene.fog.enabled = fogEnabled;
        if (fogEnabled) {
          scene.fog.density = localFogDensityForCameraHeight(heightMeters);
          scene.fog.screenSpaceErrorFactor = 3.0;
          scene.fog.minimumBrightness = 0.12;
        }
      }

      scene.requestRender();
    };

    update();
    camera.changed?.addEventListener?.(update);
    camera.moveEnd?.addEventListener?.(update);

    return () => {
      camera.changed?.removeEventListener?.(update);
      camera.moveEnd?.removeEventListener?.(update);
      restore();
    };
  }, [cameraPerspectiveId, lowModeEnabled, viewModeRoute.viewModeId, viewer]);

  useEffect(() => {
    if (!viewer) return;
    if (viewModeRoute.viewModeId === 'local') return;

    const base = baseLocalEnvironmentRef.current;
    if (!base) return;

    const scene = viewer.scene as unknown as {
      requestRender: () => void;
      fog?: {
        enabled?: boolean;
        density?: number;
        screenSpaceErrorFactor?: number;
        minimumBrightness?: number;
      };
      skyBox?: { show?: boolean };
      skyAtmosphere?: { show?: boolean };
    };

    const volumetricEnabled = !lowModeEnabled;
    let didChange = false;

    if (scene.skyBox && typeof base.skyBoxShow === 'boolean') {
      const next = volumetricEnabled ? base.skyBoxShow : false;
      if (!Object.is(scene.skyBox.show, next)) {
        scene.skyBox.show = next;
        didChange = true;
      }
    }
    if (scene.skyAtmosphere && typeof base.skyAtmosphereShow === 'boolean') {
      const next = volumetricEnabled ? base.skyAtmosphereShow : false;
      if (!Object.is(scene.skyAtmosphere.show, next)) {
        scene.skyAtmosphere.show = next;
        didChange = true;
      }
    }

    if (scene.fog && base.fog) {
      const nextEnabled = volumetricEnabled ? base.fog.enabled : false;
      if (!Object.is(scene.fog.enabled, nextEnabled)) {
        scene.fog.enabled = nextEnabled;
        didChange = true;
      }
      if (volumetricEnabled) {
        if (!Object.is(scene.fog.density, base.fog.density)) {
          scene.fog.density = base.fog.density;
          didChange = true;
        }
        if (!Object.is(scene.fog.screenSpaceErrorFactor, base.fog.screenSpaceErrorFactor)) {
          scene.fog.screenSpaceErrorFactor = base.fog.screenSpaceErrorFactor;
          didChange = true;
        }
        if (!Object.is(scene.fog.minimumBrightness, base.fog.minimumBrightness)) {
          scene.fog.minimumBrightness = base.fog.minimumBrightness;
          didChange = true;
        }
      }
    }

    if (didChange) scene.requestRender();
  }, [lowModeEnabled, viewModeRoute.viewModeId, viewer]);

  useEffect(() => {
    if (!viewer) return;

    const windArrows = windArrowsRef.current;
    if (!windArrows) return;

    let timeoutId: number | null = null;
    let lastSampleAt = 0;
    let pending = false;

    const clearTimer = () => {
      if (timeoutId == null) return;
      window.clearTimeout(timeoutId);
      timeoutId = null;
    };

    const cancelInFlight = () => {
      windAbortRef.current?.abort();
      windAbortRef.current = null;
    };

    const disableArrows = () => {
      cancelInFlight();
      windVectorsRef.current = [];
      windViewKeyRef.current = null;
      windVectorsKeyRef.current = null;
      windStyleKeyRef.current = null;
      windArrows.update({
        enabled: false,
        opacity: windLayerConfig?.opacity ?? 1,
        vectors: [],
        lowModeEnabled,
      });
    };

    const getCameraHeightMeters = (): number | null => {
      const camera = viewer.camera as unknown as { positionCartographic?: { height?: number } };
      const height = camera.positionCartographic?.height;
      if (typeof height !== 'number' || !Number.isFinite(height)) return null;
      return height;
    };

    const requestWindVectors = async (options: {
      bbox: { west: number; south: number; east: number; north: number };
      density: number;
      signal: AbortSignal;
    }): Promise<WindVector[]> => {
      if (options.bbox.east < options.bbox.west) {
        const [first, second] = await Promise.all([
          fetchWindVectorData({
            apiBaseUrl: apiBaseUrl ?? '',
            runTimeKey,
            timeKey,
            level: levelKey,
            bbox: { ...options.bbox, east: 180 },
            density: options.density,
            signal: options.signal,
          }),
          fetchWindVectorData({
            apiBaseUrl: apiBaseUrl ?? '',
            runTimeKey,
            timeKey,
            level: levelKey,
            bbox: { ...options.bbox, west: -180 },
            density: options.density,
            signal: options.signal,
          }),
        ]);
        return [...first.vectors, ...second.vectors];
      }

      const data = await fetchWindVectorData({
        apiBaseUrl: apiBaseUrl ?? '',
        runTimeKey,
        timeKey,
        level: levelKey,
        bbox: options.bbox,
        density: options.density,
        signal: options.signal,
      });
      return data.vectors;
    };

    const runUpdate = async () => {
      clearTimer();

      const windVisible = windLayerConfig?.visible === true;
      if (!apiBaseUrl || !windLayerConfig || !windVisible) {
        disableArrows();
        return;
      }

      const rectangle = viewer.camera.computeViewRectangle();
      if (!rectangle) {
        disableArrows();
        return;
      }

      const bboxRaw = {
        west: CesiumMath.toDegrees(rectangle.west),
        south: CesiumMath.toDegrees(rectangle.south),
        east: CesiumMath.toDegrees(rectangle.east),
        north: CesiumMath.toDegrees(rectangle.north),
      };

      if (!Object.values(bboxRaw).every((value) => Number.isFinite(value))) {
        disableArrows();
        return;
      }

      const bbox = {
        west: Math.round(bboxRaw.west * 100) / 100,
        south: Math.round(bboxRaw.south * 100) / 100,
        east: Math.round(bboxRaw.east * 100) / 100,
        north: Math.round(bboxRaw.north * 100) / 100,
      };

      const density = windArrowDensityForCameraHeight({
        cameraHeightMeters: getCameraHeightMeters(),
        lowModeEnabled,
      });

      const normalizedApiBaseUrl = apiBaseUrl.trim().replace(/\/+$/, '');
      const viewKey = `${normalizedApiBaseUrl}:${runTimeKey}:${timeKey}:${levelKey}:${density}:${bbox.west},${bbox.south},${bbox.east},${bbox.north}`;
      const styleKey = `${windLayerConfig.opacity}:${windVisible}:${lowModeEnabled}`;

      if (windViewKeyRef.current !== viewKey) {
        cancelInFlight();
      }
      windViewKeyRef.current = viewKey;

      const hasCurrentVectors =
        windVectorsKeyRef.current === viewKey && windVectorsRef.current.length > 0;
      if (hasCurrentVectors) {
        if (windStyleKeyRef.current !== styleKey) {
          windStyleKeyRef.current = styleKey;
          windArrows.update({
            enabled: true,
            opacity: windLayerConfig.opacity,
            vectors: windVectorsRef.current,
            lowModeEnabled,
          });
        }
        return;
      }

      if (windAbortRef.current) {
        windStyleKeyRef.current = styleKey;
        return;
      }

      const cache = windVectorsCacheRef.current;
      const cachedVectors = cache.get(viewKey);
      if (cachedVectors) {
        cancelInFlight();
        cache.delete(viewKey);
        cache.set(viewKey, cachedVectors);
        windViewKeyRef.current = viewKey;
        windVectorsKeyRef.current = viewKey;
        windStyleKeyRef.current = styleKey;
        windVectorsRef.current = cachedVectors;
        windArrows.update({
          enabled: true,
          opacity: windLayerConfig.opacity,
          vectors: cachedVectors,
          lowModeEnabled,
        });
        return;
      }

      windStyleKeyRef.current = styleKey;

      cancelInFlight();
      const controller = new AbortController();
      windAbortRef.current = controller;

      try {
        const vectors = await requestWindVectors({
          bbox,
          density,
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        if (windViewKeyRef.current !== viewKey) return;
        windVectorsRef.current = vectors;
        windVectorsKeyRef.current = viewKey;
        cache.set(viewKey, vectors);
        if (cache.size > WIND_VECTOR_CACHE_MAX_ENTRIES) {
          const oldest = cache.keys().next().value as string | undefined;
          if (oldest) cache.delete(oldest);
        }
        windArrows.update({
          enabled: true,
          opacity: windLayerConfig.opacity,
          vectors,
          lowModeEnabled,
        });
      } catch (error) {
        if (controller.signal.aborted) return;
        if (windViewKeyRef.current !== viewKey) return;
        console.warn('[Digital Earth] failed to fetch wind vectors', error);
        disableArrows();
      } finally {
        if (windAbortRef.current === controller) windAbortRef.current = null;
      }
    };

    const scheduleUpdate = () => {
      const now = Date.now();
      const elapsed = now - lastSampleAt;

      if (elapsed >= WIND_VECTOR_THROTTLE_MS && timeoutId == null) {
        lastSampleAt = now;
        void runUpdate();
        return;
      }

      pending = true;
      if (timeoutId != null) return;
      timeoutId = window.setTimeout(() => {
        timeoutId = null;
        if (!pending) return;
        pending = false;
        lastSampleAt = Date.now();
        void runUpdate();
      }, Math.max(0, WIND_VECTOR_THROTTLE_MS - elapsed));
    };

    const camera = viewer.camera as unknown as {
      changed?: { addEventListener?: (handler: () => void) => void; removeEventListener?: (handler: () => void) => void };
      moveEnd?: { addEventListener?: (handler: () => void) => void; removeEventListener?: (handler: () => void) => void };
    };

    camera.changed?.addEventListener?.(scheduleUpdate);
    camera.moveEnd?.addEventListener?.(scheduleUpdate);
    scheduleUpdate();

    return () => {
      camera.changed?.removeEventListener?.(scheduleUpdate);
      camera.moveEnd?.removeEventListener?.(scheduleUpdate);
      clearTimer();
      cancelInFlight();
    };
  }, [apiBaseUrl, levelKey, lowModeEnabled, runTimeKey, timeKey, viewer, windLayerConfig]);

  useEffect(() => {
    if (!viewer) return;

    const particles = precipitationParticlesRef.current;
    if (!particles) return;

    let timeoutId: number | null = null;
    let lastSampleAt = 0;
    let pending = false;

    const clearTimer = () => {
      if (timeoutId == null) return;
      window.clearTimeout(timeoutId);
      timeoutId = null;
    };

    const cancelInFlight = () => {
      weatherAbortRef.current?.abort();
      weatherAbortRef.current = null;
    };

    const disableParticles = () => {
      cancelInFlight();
      particles.update({
        enabled: false,
        intensity: 0,
        kind: 'none',
        lowModeEnabled,
      });
    };

    const runSample = async () => {
      clearTimer();

      const precipitationVisible = precipitationLayerConfig?.visible === true;
      const sampler = weatherSamplerRef.current;
      if (!precipitationVisible || !sampler) {
        disableParticles();
        return;
      }

      const cartographic = viewer.camera.positionCartographic;
      if (!cartographic) {
        disableParticles();
        return;
      }

      const lon = CesiumMath.toDegrees(cartographic.longitude);
      const lat = CesiumMath.toDegrees(cartographic.latitude);

      cancelInFlight();
      const controller = new AbortController();
      weatherAbortRef.current = controller;

      try {
        const sample = await sampler.sample({ lon, lat, signal: controller.signal });
        if (controller.signal.aborted) return;

        particles.update({
          enabled: true,
          intensity: sample.precipitationIntensity,
          kind: sample.precipitationKind,
          lowModeEnabled,
        });
      } catch {
        if (controller.signal.aborted) return;
        disableParticles();
      }
    };

    const scheduleSample = () => {
      const now = Date.now();
      const elapsed = now - lastSampleAt;

      if (elapsed >= WEATHER_SAMPLE_THROTTLE_MS && timeoutId == null) {
        lastSampleAt = now;
        void runSample();
        return;
      }

      pending = true;
      if (timeoutId != null) return;
      timeoutId = window.setTimeout(() => {
        timeoutId = null;
        if (!pending) return;
        pending = false;
        lastSampleAt = Date.now();
        void runSample();
      }, Math.max(0, WEATHER_SAMPLE_THROTTLE_MS - elapsed));
    };

    const camera = viewer.camera as unknown as {
      changed?: { addEventListener?: (handler: () => void) => void; removeEventListener?: (handler: () => void) => void };
      moveEnd?: { addEventListener?: (handler: () => void) => void; removeEventListener?: (handler: () => void) => void };
    };

    camera.changed?.addEventListener?.(scheduleSample);
    camera.moveEnd?.addEventListener?.(scheduleSample);
    scheduleSample();

    return () => {
      camera.changed?.removeEventListener?.(scheduleSample);
      camera.moveEnd?.removeEventListener?.(scheduleSample);
      clearTimer();
      cancelInFlight();
    };
  }, [apiBaseUrl, lowModeEnabled, precipitationLayerConfig, temperatureLayerConfig, viewer]);

  useEffect(() => {
    if (!viewer) return;
    if (!apiBaseUrl) return;
    const hasCloudLayer = layers.some((layer) => layer.type === 'cloud');
    if (!hasCloudLayer) return;

    const intervalId = window.setInterval(() => {
      setCloudFrameIndex((index) => (index + 1) % CLOUD_LAYER_FRAME_COUNT);
    }, CLOUD_LAYER_REFRESH_INTERVAL_MS);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [apiBaseUrl, layers, viewer]);

  useEffect(() => {
    if (!viewer) return;
    if (!apiBaseUrl) return;

    const existing = temperatureLayersRef.current;
    const nextIds = new Set<string>();
    const nextConfigs = layers.filter((layer) => layer.type === 'temperature');

    for (const config of nextConfigs) {
      nextIds.add(config.id);

      const params = {
        id: config.id,
        apiBaseUrl,
        timeKey,
        levelKey,
        variable: config.variable,
        opacity: config.opacity,
        visible: config.visible,
        zIndex: config.zIndex,
      };

      const current = existing.get(config.id);
      if (current) {
        current.update(params);
      } else {
        existing.set(config.id, new TemperatureLayer(viewer, params));
      }
    }

    for (const [id, layer] of existing.entries()) {
      if (nextIds.has(id)) continue;
      layer.destroy();
      existing.delete(id);
    }
  }, [apiBaseUrl, layers, levelKey, timeKey, viewer]);

  useEffect(() => {
    if (!viewer) return;
    if (!apiBaseUrl) return;

    const existing = cloudLayersRef.current;
    const nextIds = new Set<string>();
    const nextConfigs = layers.filter((layer) => layer.type === 'cloud');

    for (const config of nextConfigs) {
      nextIds.add(config.id);

      const params = {
        id: config.id,
        apiBaseUrl,
        timeKey: cloudTimeKey,
        variable: config.variable,
        levelKey:
          typeof config.level === 'number' && Number.isFinite(config.level)
            ? String(Math.round(config.level))
            : undefined,
        opacity: config.opacity,
        visible: config.visible,
        zIndex: config.zIndex,
      };

      const current = existing.get(config.id);
      if (current) {
        current.update(params);
      } else {
        existing.set(config.id, new CloudLayer(viewer, params));
      }
    }

    for (const [id, layer] of existing.entries()) {
      if (nextIds.has(id)) continue;
      layer.destroy();
      existing.delete(id);
    }
  }, [apiBaseUrl, cloudTimeKey, layers, viewer]);

  useEffect(() => {
    const stack = localCloudStackRef.current;
    if (!viewer || !stack) return;

    const enabled =
      !lowModeEnabled && viewModeRoute.viewModeId === 'local' && cameraPerspectiveId !== 'free';

    const lon = viewModeRoute.viewModeId === 'local' ? viewModeRoute.lon : Number.NaN;
    const lat = viewModeRoute.viewModeId === 'local' ? viewModeRoute.lat : Number.NaN;
    const surfaceHeightMeters =
      viewModeRoute.viewModeId === 'local' &&
      typeof viewModeRoute.heightMeters === 'number' &&
      Number.isFinite(viewModeRoute.heightMeters)
        ? viewModeRoute.heightMeters
        : 0;

    stack.update({
      enabled,
      apiBaseUrl,
      timeKey: cloudTimeKey,
      lon,
      lat,
      surfaceHeightMeters,
      layers,
    });
  }, [apiBaseUrl, cameraPerspectiveId, cloudTimeKey, layers, lowModeEnabled, viewModeRoute, viewer]);

  useEffect(() => {
    if (!viewer) return;
    if (!apiBaseUrl) return;

    const existing = precipitationLayersRef.current;
    const nextIds = new Set<string>();
    const nextConfigs = layers.filter((layer) => layer.type === 'precipitation');

    for (const config of nextConfigs) {
      nextIds.add(config.id);

      const params = {
        id: config.id,
        apiBaseUrl,
        timeKey,
        opacity: config.opacity,
        visible: config.visible,
        zIndex: config.zIndex,
        threshold: config.threshold,
      };

      const current = existing.get(config.id);
      if (current) {
        current.update(params);
      } else {
        existing.set(config.id, new PrecipitationLayer(viewer, params));
      }
    }

    for (const [id, layer] of existing.entries()) {
      if (nextIds.has(id)) continue;
      layer.destroy();
      existing.delete(id);
    }
  }, [apiBaseUrl, layers, timeKey, viewer]);

  useEffect(() => {
    if (!viewer) return;
    if (!apiBaseUrl) return;

    const existing = snowDepthLayersRef.current;
    const nextIds = new Set<string>();
    const nextConfigs = layers.filter((layer) => layer.type === 'snow-depth');

    for (const config of nextConfigs) {
      nextIds.add(config.id);

      const params = {
        id: config.id,
        apiBaseUrl,
        timeKey: snowDepthTimeKey,
        variable: config.variable,
        opacity: config.opacity,
        visible: config.visible,
        zIndex: config.zIndex,
        rectangle: viewModeRoute.viewModeId === 'event' ? eventMonitoringRectangle : null,
      };

      const current = existing.get(config.id);
      if (current) {
        current.update(params);
      } else {
        existing.set(config.id, new SnowDepthLayer(viewer, params));
      }
    }

    for (const [id, layer] of existing.entries()) {
      if (nextIds.has(id)) continue;
      layer.destroy();
      existing.delete(id);
    }
  }, [apiBaseUrl, eventMonitoringRectangle, layers, snowDepthTimeKey, viewModeRoute.viewModeId, viewer]);

  useEffect(() => {
    if (!viewer) return;

    const sorted = [...layers].sort(sortByZIndex);
    let didReorder = false;
    for (const config of sorted) {
      const layer =
        temperatureLayersRef.current.get(config.id)?.layer ??
        cloudLayersRef.current.get(config.id)?.layer ??
        precipitationLayersRef.current.get(config.id)?.layer ??
        snowDepthLayersRef.current.get(config.id)?.layer;
      if (!layer) continue;
      viewer.imageryLayers.raiseToTop(layer);
      didReorder = true;
    }
    if (didReorder) {
      viewer.scene.requestRender();
    }
  }, [apiBaseUrl, cloudTimeKey, layers, timeKey, viewer]);

  return (
    <div className="viewerRoot">
      <div ref={containerRef} className="viewerCanvas" data-testid="cesium-container" />
      <div id="effect-stage" className="absolute inset-0 z-0 pointer-events-none" />
      {viewer ? (
        <AircraftDemoLayer
          viewer={viewer}
          viewModeRoute={viewModeRoute}
          cameraPerspectiveId={cameraPerspectiveId}
        />
      ) : null}
      <div className="viewerOverlay">
        {viewer ? <CompassControl viewer={viewer} /> : null}
        {viewModeRoute.viewModeId === 'event' ? (
          <EventLayersToggle
            historyStatus={eventHistoricalLayerStatus}
            differenceStatus={eventBiasLayerStatus}
          />
        ) : null}
        {terrainNotice ? (
          <div className="terrainNoticePanel" role="alert" aria-label="terrain-notice">
            <div className="terrainNoticeTitle">地形</div>
            <div className="terrainNoticeMessage">{terrainNotice}</div>
          </div>
        ) : null}
        {monitoringNotice ? (
          <div className="terrainNoticePanel" role="alert" aria-label="monitoring-notice">
            <div className="terrainNoticeTitle">监测</div>
            <div className="terrainNoticeMessage">{monitoringNotice}</div>
          </div>
        ) : null}
        {performanceNotice ? (
          <div className="terrainNoticePanel" role="alert" aria-label="performance-notice">
            <div className="terrainNoticeTitle">性能</div>
            <div className="terrainNoticeMessage">
              检测到帧率较低（{performanceNotice.fps} FPS），建议切换到 Low 模式以提升性能。
            </div>
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                className="rounded-lg border border-slate-400/20 bg-slate-700/30 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
                onClick={() => setPerformanceMode('low')}
              >
                切换到 Low
              </button>
              <button
                type="button"
                className="rounded-lg border border-slate-400/20 bg-slate-700/30 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
                onClick={() => setPerformanceNotice(null)}
              >
                忽略
              </button>
            </div>
          </div>
        ) : null}
      </div>
	      <div
	        className="absolute top-24 z-60 flex flex-col gap-3"
	        style={{
	          right: (infoPanelCollapsed ? 48 : 360) + 16 + 12,
	        }}
	      >
	        {viewModeRoute.viewModeId === 'local' ? (
	          <LocalInfoPanel
	            lat={viewModeRoute.lat}
	            lon={viewModeRoute.lon}
            heightMeters={viewModeRoute.heightMeters}
            timeKey={localTimeKey}
            activeLayer={activeLayer}
            canGoBack={canGoBack}
            onBack={() => goBack()}
            onLockLayer={() => {
              if (!activeLayer) return;
              enterLayerGlobal({ layerId: activeLayer.id });
            }}
          />
        ) : null}
        <RiskPoiPopup
          poi={riskPopup?.poi ?? null}
          evaluation={riskPopup?.evaluation ?? null}
          status={riskPopup?.status ?? 'loaded'}
          errorMessage={riskPopup?.errorMessage ?? null}
          onClose={() => {
            riskPopupAbortRef.current?.abort();
            riskPopupAbortRef.current = null;
            setRiskPopup(null);
          }}
          onOpenDisasterDemo={() => setDisasterDemoOpen(true)}
        />
        <SamplingCard state={samplingCardState} onClose={closeSamplingCard} />
      </div>
      {disasterDemoOpen ? (
        <div
          className="modalOverlay"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setDisasterDemoOpen(false);
          }}
        >
          <div className="modal" role="dialog" aria-modal="true" aria-label="灾害演示">
            <div className="modalHeader">
              <div>
                <h2 className="modalTitle">灾害演示</h2>
                <div className="modalMeta">灾害特效预设与播放控制</div>
              </div>
              <div className="modalHeaderActions">
                <button
                  type="button"
                  className="modalButton"
                  onClick={() => setDisasterDemoOpen(false)}
                >
                  关闭
                </button>
              </div>
            </div>
            <div className="modalBody">
              {apiBaseUrl ? (
                <DisasterDemo apiBaseUrl={apiBaseUrl} />
              ) : (
                <div className="muted">缺少 API 配置</div>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
