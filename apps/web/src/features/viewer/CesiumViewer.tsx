import {
  Cartographic,
  Cartesian3,
  CesiumTerrainProvider,
  Color,
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
  ScreenSpaceEventType,
  UrlTemplateImageryProvider,
  Viewer,
  WebMercatorTilingScheme,
  type Viewer as CesiumViewerInstance
} from 'cesium';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { loadConfig, type MapConfig } from '../../config';
import { getBasemapById, type BasemapId } from '../../config/basemaps';
import { useBasemapStore } from '../../state/basemap';
import { useCameraPerspectiveStore, type CameraPerspectiveId } from '../../state/cameraPerspective';
import { resolveEventLayerTemplateSpec, useEventAutoLayersStore } from '../../state/eventAutoLayers';
import { useLayerManagerStore, type LayerConfig, type LayerType } from '../../state/layerManager';
import { usePerformanceModeStore } from '../../state/performanceMode';
import { useSceneModeStore } from '../../state/sceneMode';
import { useViewModeStore, type ViewModeRoute } from '../../state/viewMode';
import { PrecipitationParticles } from '../effects/PrecipitationParticles';
import { WindArrows, windArrowDensityForCameraHeight } from '../effects/WindArrows';
import { createCloudSampler, createWeatherSampler } from '../effects/weatherSampler';
import { CloudLayer } from '../layers/CloudLayer';
import { PrecipitationLayer } from '../layers/PrecipitationLayer';
import { TemperatureLayer } from '../layers/TemperatureLayer';
import {
  buildCldasTileUrlTemplate,
  buildCloudTileUrlTemplate,
  buildPrecipitationTileUrlTemplate,
  fetchWindVectorData,
  type WindVector,
} from '../layers/layersApi';
import { LocalInfoPanel } from '../local/LocalInfoPanel';
import { SamplingCard } from '../sampling/SamplingCard';
import { useSamplingCard } from '../sampling/useSamplingCard';
import { BasemapSelector } from './BasemapSelector';
import { CompassControl } from './CompassControl';
import { EventLayersToggle } from './EventLayersToggle';
import { SceneModeToggle } from './SceneModeToggle';
import { createImageryProviderForBasemap, setViewerBasemap, setViewerImageryProvider } from './cesiumBasemap';
import { switchViewerSceneMode } from './cesiumSceneMode';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import { getProductDetail } from '../products/productsApi';
import type { BBox, ProductHazardDetail } from '../products/productsTypes';
import { extractGeoJsonPolygons, type LonLat } from './geoJsonPolygons';

const DEFAULT_CAMERA = {
  longitude: 116.391,
  latitude: 39.9075,
  heightMeters: 20_000_000
} as const;

const MIN_ZOOM_DISTANCE_METERS = 100;
const MAX_ZOOM_DISTANCE_METERS = 40_000_000;

const DEFAULT_LAYER_TIME_KEY = '2024-01-15T00:00:00Z';
const CLOUD_LAYER_REFRESH_INTERVAL_MS = 5 * 60 * 1000;
const CLOUD_LAYER_FRAME_COUNT = 24;
const CLOUD_LAYER_FRAME_STEP_MS = 60 * 60 * 1000;
const WEATHER_SAMPLE_THROTTLE_MS = 750;
const WEATHER_SAMPLE_ZOOM = 8;
const WIND_VECTOR_THROTTLE_MS = 800;
const WIND_ARROWS_MAX_COUNT = 500;
const WIND_VECTOR_CACHE_MAX_ENTRIES = 20;

const LOCAL_FREE_PITCH = -Math.PI / 4;
const LOCAL_FORWARD_PITCH = 0;
const LOCAL_UPWARD_PITCH = CesiumMath.PI_OVER_TWO - Math.PI / 12;

const LAYER_GLOBAL_SHELL_HEIGHT_METERS_BY_LAYER_TYPE: Record<LayerType, number> = {
  temperature: 2000,
  cloud: 5000,
  precipitation: 3000,
  wind: 8000,
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

function cameraPitchForPerspective(cameraPerspectiveId: CameraPerspectiveId): number | null {
  if (cameraPerspectiveId === 'upward') return LOCAL_UPWARD_PITCH;
  if (cameraPerspectiveId === 'forward') return LOCAL_FORWARD_PITCH;
  return null;
}

function getViewerCameraHeightMeters(viewer: CesiumViewerInstance): number | null {
  const camera = viewer.camera as unknown as { positionCartographic?: { height?: number } };
  const height = camera.positionCartographic?.height;
  if (typeof height !== 'number' || !Number.isFinite(height)) return null;
  return height;
}

function localFrustumForCameraHeight(heightMeters: number): { near: number; far: number } {
  const near = clampNumber(heightMeters * 0.0005, 0.2, 5);
  const far = clampNumber(heightMeters * 400, 50_000, 2_000_000);
  return { near, far: Math.max(far, near + 1) };
}

function localFogDensityForCameraHeight(heightMeters: number): number {
  const normalized = clampNumber(heightMeters / 12_000, 0, 1);
  return 0.00055 * (1 - normalized) + 0.00005;
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

function normalizeSelfHostedBasemapTemplate(
  urlTemplate: string,
  scheme: 'xyz' | 'tms',
): string {
  if (scheme !== 'tms') return urlTemplate;
  if (urlTemplate.includes('{reverseY}')) return urlTemplate;
  return urlTemplate.replaceAll('{y}', '{reverseY}');
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

export function CesiumViewer() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [viewer, setViewer] = useState<CesiumViewerInstance | null>(null);
  const [mapConfig, setMapConfig] = useState<MapConfig | undefined>(undefined);
  const [apiBaseUrl, setApiBaseUrl] = useState<string | null>(null);
  const [terrainNotice, setTerrainNotice] = useState<string | null>(null);
  const basemapId = useBasemapStore((state) => state.basemapId);
  const sceneModeId = useSceneModeStore((state) => state.sceneModeId);
  const viewModeRoute = useViewModeStore((state) => state.route);
  const viewModeTransition = useViewModeStore((state) => state.transition);
  const enterLocal = useViewModeStore((state) => state.enterLocal);
  const enterLayerGlobal = useViewModeStore((state) => state.enterLayerGlobal);
  const canGoBack = useViewModeStore((state) => state.canGoBack);
  const goBack = useViewModeStore((state) => state.goBack);
  const layers = useLayerManagerStore((state) => state.layers);
  const performanceModeEnabled = usePerformanceModeStore((state) => state.enabled);
  const cameraPerspectiveId = useCameraPerspectiveStore((state) => state.cameraPerspectiveId);
  const appliedBasemapIdRef = useRef<BasemapId | null>(null);
  const didApplySceneModeRef = useRef(false);
  const localEntryKeyRef = useRef<string | null>(null);
  const layerGlobalEntryKeyRef = useRef<string | null>(null);
  const eventEntryKeyRef = useRef<string | null>(null);
  const appliedCameraPerspectiveRef = useRef<CameraPerspectiveId | null>(null);
  const eventAbortRef = useRef<AbortController | null>(null);
  const eventEntitiesRef = useRef<Entity[]>([]);
  const baseCameraControllerRef = useRef<{ enableTilt?: boolean; enableLook?: boolean } | null>(
    null,
  );
  const baseLocalEnvironmentRef = useRef<{
    fog?: {
      enabled?: boolean;
      density?: number;
      screenSpaceErrorFactor?: number;
      minimumBrightness?: number;
    };
    skyBoxShow?: boolean;
    skyAtmosphereShow?: boolean;
    frustum?: { near?: number; far?: number };
  } | null>(null);
  const temperatureLayersRef = useRef<Map<string, TemperatureLayer>>(new Map());
  const cloudLayersRef = useRef<Map<string, CloudLayer>>(new Map());
  const precipitationLayersRef = useRef<Map<string, PrecipitationLayer>>(new Map());
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
  const [cloudFrameIndex, setCloudFrameIndex] = useState(0);
  const localModeSnapshotRef = useRef<ModeSnapshot | null>(null);
  const pendingLocalCameraRestoreRef = useRef<SavedCameraState | null>(null);
  const previousRouteRef = useRef<ViewModeRoute | null>(null);
  const eventModeLayersSnapshotRef = useRef<LayerConfig[] | null>(null);
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
    () => makeHourlyUtcIso(DEFAULT_LAYER_TIME_KEY, cloudFrameIndex),
    [cloudFrameIndex],
  );

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
    return DEFAULT_LAYER_TIME_KEY;
  }, [activeLayer, cloudTimeKey]);

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
    if (!viewer) return;

    if (!baseCameraControllerRef.current) {
      const controller = viewer.scene.screenSpaceCameraController as unknown as {
        enableTilt?: boolean;
        enableLook?: boolean;
      };
      baseCameraControllerRef.current = {
        enableTilt: controller.enableTilt,
        enableLook: controller.enableLook,
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
      const frustum = viewer.camera.frustum as unknown as { near?: number; far?: number };

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
    const initialBasemap = getBasemapById(initialBasemapId);
    if (!initialBasemap) {
      throw new Error(`Unknown basemap id: ${initialBasemapId}`);
    }
    appliedBasemapIdRef.current = initialBasemapId;

    const newViewer = new Viewer(containerRef.current!, {
      baseLayer: new ImageryLayer(
        // Avoid Cesium ion default imagery (Bing) by always passing an explicit base layer.
        createImageryProviderForBasemap(initialBasemap),
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
      newViewer.destroy();
    };
  }, []);

  useEffect(() => {
    if (!viewer) return;
    if (basemapProvider !== 'open') return;
    if (appliedBasemapIdRef.current === basemapId) return;
    const basemap = getBasemapById(basemapId);
    if (!basemap) return;

    setViewerBasemap(viewer, basemap);
    appliedBasemapIdRef.current = basemapId;
  }, [basemapId, basemapProvider, viewer]);

  useEffect(() => {
    const token = mapConfig?.cesiumIonAccessToken;
    if (!token) return;
    Ion.defaultAccessToken = token;
  }, [mapConfig?.cesiumIonAccessToken]);

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
          url: normalizeSelfHostedBasemapTemplate(urlTemplate, scheme),
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
    if (!mapConfig) return;
    if (viewModeRoute.viewModeId === 'layerGlobal') return;

    let cancelled = false;

    const applyTerrainProvider = async () => {
      setTerrainNotice(null);

      if (mapConfig.terrainProvider === 'none' || mapConfig.terrainProvider === undefined) {
        viewer.terrainProvider = new EllipsoidTerrainProvider();
        viewer.scene.requestRender();
        return;
      }

      if (mapConfig.terrainProvider === 'ion') {
        const token = mapConfig.cesiumIonAccessToken;
        if (!token) {
          console.warn('[Digital Earth] map.terrainProvider=ion requires map.cesiumIonAccessToken');
          setTerrainNotice('未配置 Cesium ion token，已回退到无地形模式。');
          viewer.terrainProvider = new EllipsoidTerrainProvider();
          viewer.scene.requestRender();
          return;
        }
        const terrain = await createWorldTerrainAsync();
        if (cancelled) return;
        viewer.terrainProvider = terrain;
        viewer.scene.requestRender();
        return;
      }

      if (mapConfig.terrainProvider === 'selfHosted') {
        const terrainUrl = mapConfig.selfHosted?.terrainUrl;
        if (!terrainUrl) {
          console.warn('[Digital Earth] map.terrainProvider=selfHosted requires map.selfHosted.terrainUrl');
          setTerrainNotice('未配置自建地形地址，已回退到无地形模式。');
          viewer.terrainProvider = new EllipsoidTerrainProvider();
          viewer.scene.requestRender();
          return;
        }
        const terrain = await CesiumTerrainProvider.fromUrl(terrainUrl);
        if (cancelled) return;
        viewer.terrainProvider = terrain;
        viewer.scene.requestRender();
      }
    };

    void applyTerrainProvider().catch((error: unknown) => {
      if (cancelled) return;
      console.warn('[Digital Earth] failed to apply terrain provider', error);
      setTerrainNotice('地形加载失败，已回退到无地形模式。');
      viewer.terrainProvider = new EllipsoidTerrainProvider();
      viewer.scene.requestRender();
    });

    return () => {
      cancelled = true;
    };
  }, [mapConfig, viewModeRoute.viewModeId, viewer]);

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
      maxArrowsPerformance: 0,
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

  const windLayerConfig = useMemo(() => {
    const visible = layers.find((layer) => layer.type === 'wind' && layer.visible);
    return visible ?? layers.find((layer) => layer.type === 'wind') ?? null;
  }, [layers]);

  const temperatureLayerConfig = useMemo(() => {
    const visible = layers.find((layer) => layer.type === 'temperature' && layer.visible);
    return visible ?? layers.find((layer) => layer.type === 'temperature') ?? null;
  }, [layers]);

  const cloudLayerConfig = useMemo(() => {
    const visible = layers.find((layer) => layer.type === 'cloud' && layer.visible);
    return visible ?? layers.find((layer) => layer.type === 'cloud') ?? null;
  }, [layers]);

  useEffect(() => {
    if (!apiBaseUrl) return;
    if (!precipitationLayerConfig) {
      weatherSamplerRef.current = null;
      return;
    }

    const precipitationTemplate = buildPrecipitationTileUrlTemplate({
      apiBaseUrl,
      timeKey: DEFAULT_LAYER_TIME_KEY,
      threshold: precipitationLayerConfig.threshold,
    });

    const temperatureVariable = (temperatureLayerConfig?.variable || 'TMP').trim() || 'TMP';
    const temperatureTemplate = buildCldasTileUrlTemplate({
      apiBaseUrl,
      timeKey: DEFAULT_LAYER_TIME_KEY,
      variable: temperatureVariable.toUpperCase(),
    });

    weatherSamplerRef.current = createWeatherSampler({
      zoom: WEATHER_SAMPLE_ZOOM,
      precipitation: { urlTemplate: precipitationTemplate },
      temperature: { urlTemplate: temperatureTemplate },
    });
  }, [apiBaseUrl, precipitationLayerConfig, temperatureLayerConfig]);

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
  }, [closeSamplingCard, enterLocal, openSamplingCard, setSamplingData, setSamplingError, viewer]);

  useEffect(() => {
    if (!viewer) return;
    if (viewModeRoute.viewModeId !== 'local') {
      localEntryKeyRef.current = null;
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

    const offsetMeters = sceneModeId === '2d' ? 5000 : 3000;
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
  }, [cameraPerspectiveId, sceneModeId, viewModeRoute, viewer]);

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
        maybeApplyEventAutoLayerTemplate();

        const hazards = product.hazards;
        const destinationBBox = bboxUnion(hazards.map((hazard) => hazard.bbox));

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
        viewer.scene.requestRender();
      } finally {
        if (eventAbortRef.current === controller) eventAbortRef.current = null;
      }
    })();

    return () => controller.abort();
  }, [apiBaseUrl, maybeApplyEventAutoLayerTemplate, sceneModeId, viewModeRoute, viewer]);

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

    const key = `${sceneModeId}:${viewModeRoute.layerId}:${shellHeightMeters}`;
    if (layerGlobalEntryKeyRef.current === key) return;
    layerGlobalEntryKeyRef.current = key;

    if (targetLayer && !targetLayer.visible) {
      useLayerManagerStore.getState().setLayerVisible(targetLayer.id, true);
    }

    const heightOffsetMeters = Math.max(shellHeightMeters * 0.5, 1000);
    const destination = Cartesian3.fromDegrees(0, 0, shellHeightMeters + heightOffsetMeters);
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
    const baseEllipsoid = globe.ellipsoid;
    const baseTerrainProvider = viewer.terrainProvider;

    const radii = baseEllipsoid.radii;
    const shellEllipsoid = new Ellipsoid(
      radii.x + layerGlobalShellHeightMeters,
      radii.y + layerGlobalShellHeightMeters,
      radii.z + layerGlobalShellHeightMeters,
    );

    globe.ellipsoid = shellEllipsoid;
    viewer.terrainProvider = new EllipsoidTerrainProvider({ ellipsoid: shellEllipsoid });
    viewer.scene.requestRender();

    return () => {
      globe.ellipsoid = baseEllipsoid;
      viewer.terrainProvider = baseTerrainProvider;
      viewer.scene.requestRender();
    };
  }, [layerGlobalShellHeightMeters, sceneModeId, viewer]);

  useEffect(() => {
    if (!viewer) return;

    const controller = viewer.scene.screenSpaceCameraController as unknown as {
      enableTilt?: boolean;
      enableLook?: boolean;
    };
    const baseController = baseCameraControllerRef.current;

    if (viewModeRoute.viewModeId !== 'local') {
      const previous = appliedCameraPerspectiveRef.current;
      appliedCameraPerspectiveRef.current = null;

      if (previous && previous !== 'free') {
        if (baseController && typeof baseController.enableTilt === 'boolean') {
          controller.enableTilt = baseController.enableTilt;
        }
        if (baseController && typeof baseController.enableLook === 'boolean') {
          controller.enableLook = baseController.enableLook;
        }
        viewer.scene.requestRender();
      }
      return;
    }

    if (cameraPerspectiveId === 'free') {
      if (baseController && typeof baseController.enableTilt === 'boolean') {
        controller.enableTilt = baseController.enableTilt;
      }
      if (baseController && typeof baseController.enableLook === 'boolean') {
        controller.enableLook = baseController.enableLook;
      }
      viewer.scene.requestRender();
      appliedCameraPerspectiveRef.current = cameraPerspectiveId;
      return;
    }

    controller.enableTilt = false;
    controller.enableLook = false;

    if (appliedCameraPerspectiveRef.current === cameraPerspectiveId) {
      viewer.scene.requestRender();
      return;
    }

    appliedCameraPerspectiveRef.current = cameraPerspectiveId;
    const pitch = cameraPitchForPerspective(cameraPerspectiveId) ?? LOCAL_FREE_PITCH;
    viewer.camera.flyTo({
      destination: Cartesian3.clone(viewer.camera.position),
      orientation: {
        heading: viewer.camera.heading,
        pitch,
        roll: 0,
      },
      duration: 0.6,
    });
  }, [cameraPerspectiveId, viewModeRoute.viewModeId, viewer]);

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
      frustum?: { near?: number; far?: number };
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
      }
      scene.requestRender();
    };

    const update = () => {
      if (scene.skyBox) scene.skyBox.show = true;
      if (scene.skyAtmosphere) scene.skyAtmosphere.show = true;

      const heightMeters = getViewerCameraHeightMeters(viewer) ?? 0;

      if (camera.frustum) {
        const { near, far } = localFrustumForCameraHeight(heightMeters);
        camera.frustum.near = near;
        camera.frustum.far = far;
      }

      if (scene.fog) {
        scene.fog.enabled = true;
        scene.fog.density = localFogDensityForCameraHeight(heightMeters);
        scene.fog.screenSpaceErrorFactor = 3.0;
        scene.fog.minimumBrightness = 0.12;
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
  }, [viewModeRoute.viewModeId, viewer]);

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
        performanceModeEnabled,
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
            timeKey: DEFAULT_LAYER_TIME_KEY,
            bbox: { ...options.bbox, east: 180 },
            density: options.density,
            signal: options.signal,
          }),
          fetchWindVectorData({
            apiBaseUrl: apiBaseUrl ?? '',
            timeKey: DEFAULT_LAYER_TIME_KEY,
            bbox: { ...options.bbox, west: -180 },
            density: options.density,
            signal: options.signal,
          }),
        ]);
        return [...first.vectors, ...second.vectors];
      }

      const data = await fetchWindVectorData({
        apiBaseUrl: apiBaseUrl ?? '',
        timeKey: DEFAULT_LAYER_TIME_KEY,
        bbox: options.bbox,
        density: options.density,
        signal: options.signal,
      });
      return data.vectors;
    };

    const runUpdate = async () => {
      clearTimer();

      const windVisible = windLayerConfig?.visible === true;
      if (!apiBaseUrl || !windLayerConfig || !windVisible || performanceModeEnabled) {
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
        performanceModeEnabled,
      });

      const normalizedApiBaseUrl = apiBaseUrl.trim().replace(/\/+$/, '');
      const viewKey = `${normalizedApiBaseUrl}:${DEFAULT_LAYER_TIME_KEY}:${density}:${bbox.west},${bbox.south},${bbox.east},${bbox.north}`;
      const styleKey = `${windLayerConfig.opacity}:${windVisible}:${performanceModeEnabled}`;

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
            performanceModeEnabled,
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
          performanceModeEnabled,
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
          performanceModeEnabled,
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
  }, [apiBaseUrl, performanceModeEnabled, viewer, windLayerConfig]);

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
        performanceModeEnabled,
      });
    };

    const runSample = async () => {
      clearTimer();

      const precipitationVisible = precipitationLayerConfig?.visible === true;
      const sampler = weatherSamplerRef.current;
      if (!precipitationVisible || performanceModeEnabled || !sampler) {
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
          performanceModeEnabled,
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
  }, [apiBaseUrl, performanceModeEnabled, precipitationLayerConfig, temperatureLayerConfig, viewer]);

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
        timeKey: DEFAULT_LAYER_TIME_KEY,
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
  }, [apiBaseUrl, layers, viewer]);

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
        timeKey: DEFAULT_LAYER_TIME_KEY,
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
  }, [apiBaseUrl, layers, viewer]);

  useEffect(() => {
    if (!viewer) return;

    const sorted = [...layers].sort(sortByZIndex);
    let didReorder = false;
    for (const config of sorted) {
      const layer =
        temperatureLayersRef.current.get(config.id)?.layer ??
        cloudLayersRef.current.get(config.id)?.layer ??
        precipitationLayersRef.current.get(config.id)?.layer;
      if (!layer) continue;
      viewer.imageryLayers.raiseToTop(layer);
      didReorder = true;
    }
    if (didReorder) {
      viewer.scene.requestRender();
    }
  }, [apiBaseUrl, cloudTimeKey, layers, viewer]);

  return (
    <div className="viewerRoot">
      <div ref={containerRef} className="viewerCanvas" data-testid="cesium-container" />
      <div className="viewerOverlay">
        {viewer ? <CompassControl viewer={viewer} /> : null}
        <SceneModeToggle />
        <EventLayersToggle />
        {basemapProvider === 'open' ? <BasemapSelector /> : null}
        {terrainNotice ? (
          <div className="terrainNoticePanel" role="alert" aria-label="terrain-notice">
            <div className="terrainNoticeTitle">地形</div>
            <div className="terrainNoticeMessage">{terrainNotice}</div>
          </div>
        ) : null}
      </div>
      <div className="absolute right-3 top-3 z-20 flex flex-col gap-3">
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
        <SamplingCard state={samplingCardState} onClose={closeSamplingCard} />
      </div>
    </div>
  );
}
