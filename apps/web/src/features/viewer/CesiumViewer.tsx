import {
  Cartesian3,
  CesiumTerrainProvider,
  createWorldImageryAsync,
  createWorldTerrainAsync,
  EllipsoidTerrainProvider,
  ImageryLayer,
  Ion,
  UrlTemplateImageryProvider,
  Viewer,
  WebMercatorTilingScheme,
  type Viewer as CesiumViewerInstance
} from 'cesium';
import { useEffect, useRef, useState } from 'react';
import { loadConfig, type MapConfig } from '../../config';
import { getBasemapById, type BasemapId } from '../../config/basemaps';
import { useBasemapStore } from '../../state/basemap';
import { useSceneModeStore } from '../../state/sceneMode';
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
  const [terrainNotice, setTerrainNotice] = useState<string | null>(null);
  const basemapId = useBasemapStore((state) => state.basemapId);
  const sceneModeId = useSceneModeStore((state) => state.sceneModeId);
  const appliedBasemapIdRef = useRef<BasemapId | null>(null);
  const didApplySceneModeRef = useRef(false);

  const basemapProvider = mapConfig?.basemapProvider ?? 'open';

  useEffect(() => {
    let cancelled = false;
    void loadConfig()
      .then((config) => {
        if (cancelled) return;
        setMapConfig(config.map);
      })
      .catch(() => {
        if (cancelled) return;
        setMapConfig(undefined);
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
