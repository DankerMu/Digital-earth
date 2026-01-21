import {
  Cartesian3,
  CesiumTerrainProvider,
  createWorldImageryAsync,
  createWorldTerrainAsync,
  EllipsoidTerrainProvider,
  ImageryLayer,
  Ion,
  Math as CesiumMath,
  UrlTemplateImageryProvider,
  Viewer,
  WebMercatorTilingScheme,
  type Viewer as CesiumViewerInstance
} from 'cesium';
import { useEffect, useMemo, useRef, useState } from 'react';
import { loadConfig, type MapConfig } from '../../config';
import { getBasemapById, type BasemapId } from '../../config/basemaps';
import { useBasemapStore } from '../../state/basemap';
import { useLayerManagerStore } from '../../state/layerManager';
import { usePerformanceModeStore } from '../../state/performanceMode';
import { useSceneModeStore } from '../../state/sceneMode';
import { PrecipitationParticles } from '../effects/PrecipitationParticles';
import { createWeatherSampler } from '../effects/weatherSampler';
import { CloudLayer } from '../layers/CloudLayer';
import { PrecipitationLayer } from '../layers/PrecipitationLayer';
import { TemperatureLayer } from '../layers/TemperatureLayer';
import { buildCldasTileUrlTemplate, buildPrecipitationTileUrlTemplate } from '../layers/layersApi';
import { BasemapSelector } from './BasemapSelector';
import { CompassControl } from './CompassControl';
import { EventLayersToggle } from './EventLayersToggle';
import { SceneModeToggle } from './SceneModeToggle';
import { createImageryProviderForBasemap, setViewerBasemap, setViewerImageryProvider } from './cesiumBasemap';
import { switchViewerSceneMode } from './cesiumSceneMode';
import 'cesium/Build/Cesium/Widgets/widgets.css';

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

function normalizeSelfHostedBasemapTemplate(
  urlTemplate: string,
  scheme: 'xyz' | 'tms',
): string {
  if (scheme !== 'tms') return urlTemplate;
  if (urlTemplate.includes('{reverseY}')) return urlTemplate;
  return urlTemplate.replaceAll('{y}', '{reverseY}');
}

export function CesiumViewer() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [viewer, setViewer] = useState<CesiumViewerInstance | null>(null);
  const [mapConfig, setMapConfig] = useState<MapConfig | undefined>(undefined);
  const [apiBaseUrl, setApiBaseUrl] = useState<string | null>(null);
  const [terrainNotice, setTerrainNotice] = useState<string | null>(null);
  const basemapId = useBasemapStore((state) => state.basemapId);
  const sceneModeId = useSceneModeStore((state) => state.sceneModeId);
  const layers = useLayerManagerStore((state) => state.layers);
  const performanceModeEnabled = usePerformanceModeStore((state) => state.enabled);
  const appliedBasemapIdRef = useRef<BasemapId | null>(null);
  const didApplySceneModeRef = useRef(false);
  const temperatureLayersRef = useRef<Map<string, TemperatureLayer>>(new Map());
  const cloudLayersRef = useRef<Map<string, CloudLayer>>(new Map());
  const precipitationLayersRef = useRef<Map<string, PrecipitationLayer>>(new Map());
  const precipitationParticlesRef = useRef<PrecipitationParticles | null>(null);
  const weatherSamplerRef = useRef<ReturnType<typeof createWeatherSampler> | null>(null);
  const weatherAbortRef = useRef<AbortController | null>(null);
  const [cloudFrameIndex, setCloudFrameIndex] = useState(0);
  const cloudTimeKey = useMemo(
    () => makeHourlyUtcIso(DEFAULT_LAYER_TIME_KEY, cloudFrameIndex),
    [cloudFrameIndex],
  );

  const basemapProvider = mapConfig?.basemapProvider ?? 'open';

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
    if (!viewer) return;
    if (!mapConfig) return;

    let cancelled = false;

    const token = mapConfig.cesiumIonAccessToken;
    if (token) {
      Ion.defaultAccessToken = token;
    }

    const applyBasemapProvider = async () => {
      if (mapConfig.basemapProvider !== 'ion') return;
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

    const applyTerrainProvider = async () => {
      setTerrainNotice(null);

      if (mapConfig.terrainProvider === 'none' || mapConfig.terrainProvider === undefined) {
        viewer.terrainProvider = new EllipsoidTerrainProvider();
        viewer.scene.requestRender();
        return;
      }

      if (mapConfig.terrainProvider === 'ion') {
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

    void applyBasemapProvider().catch((error: unknown) => {
      if (cancelled) return;
      console.warn('[Digital Earth] failed to apply basemap provider', error);
    });

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
  }, [mapConfig, viewer]);

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

  const precipitationLayerConfig = useMemo(() => {
    const visible = layers.find((layer) => layer.type === 'precipitation' && layer.visible);
    return visible ?? layers.find((layer) => layer.type === 'precipitation') ?? null;
  }, [layers]);

  const temperatureLayerConfig = useMemo(() => {
    const visible = layers.find((layer) => layer.type === 'temperature' && layer.visible);
    return visible ?? layers.find((layer) => layer.type === 'temperature') ?? null;
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
    for (const config of sorted) {
      const layer =
        temperatureLayersRef.current.get(config.id)?.layer ??
        cloudLayersRef.current.get(config.id)?.layer ??
        precipitationLayersRef.current.get(config.id)?.layer;
      if (!layer) continue;
      viewer.imageryLayers.raiseToTop(layer);
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
    </div>
  );
}
