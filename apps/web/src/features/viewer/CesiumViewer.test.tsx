import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const precipitationParticlesMocks = vi.hoisted(() => {
  return {
    update: vi.fn(),
    destroy: vi.fn(),
    instances: [] as Array<{ update: (args: unknown) => void; destroy: () => void }>,
  };
});

vi.mock('../effects/PrecipitationParticles', () => {
  return {
    PrecipitationParticles: vi.fn(function () {
      const instance = {
        update: precipitationParticlesMocks.update,
        destroy: precipitationParticlesMocks.destroy,
      };
      precipitationParticlesMocks.instances.push(instance);
      return instance;
    }),
  };
});

const windArrowsMocks = vi.hoisted(() => {
  return {
    update: vi.fn(),
    destroy: vi.fn(),
    instances: [] as Array<{ update: (args: unknown) => void; destroy: () => void }>,
    density: vi.fn(() => 12),
  };
});

const customDataSourceMocks = vi.hoisted(() => {
  return {
    instances: [] as Array<{
      name: string;
      entities: { add: ReturnType<typeof vi.fn>; removeAll: ReturnType<typeof vi.fn> };
      clustering: {
        enabled: boolean;
        pixelRange: number;
        minimumClusterSize: number;
        clusterEvent: { addEventListener: ReturnType<typeof vi.fn>; removeEventListener: ReturnType<typeof vi.fn> };
      };
    }>,
  };
});

vi.mock('../effects/WindArrows', () => {
  return {
    WindArrows: vi.fn(function () {
      const instance = {
        update: windArrowsMocks.update,
        destroy: windArrowsMocks.destroy,
      };
      windArrowsMocks.instances.push(instance);
      return instance;
    }),
    windArrowDensityForCameraHeight: windArrowsMocks.density,
  };
});

const weatherSamplerMocks = vi.hoisted(() => {
  return {
    sample: vi.fn(async (): Promise<{
      precipitationMm: number | null;
      precipitationIntensity: number;
      precipitationKind: 'none' | 'rain' | 'snow';
      temperatureC: number | null;
    }> => ({
      precipitationMm: null,
      precipitationIntensity: 0,
      precipitationKind: 'none',
      temperatureC: null,
    })),
  };
});

const cloudSamplerMocks = vi.hoisted(() => {
  return {
    sample: vi.fn(async (): Promise<{ cloudCoverFraction: number | null }> => ({
      cloudCoverFraction: null,
    })),
  };
});

vi.mock('../effects/weatherSampler', () => {
  return {
    createWeatherSampler: vi.fn(() => ({
      sample: weatherSamplerMocks.sample,
    })),
    createCloudSampler: vi.fn(() => ({
      sample: cloudSamplerMocks.sample,
    })),
  };
});

vi.mock('cesium', () => {
  const SceneMode = {
    MORPHING: 0,
    COLUMBUS_VIEW: 1,
    SCENE2D: 2,
    SCENE3D: 3
  };

  const ScreenSpaceEventType = {
    LEFT_CLICK: 0,
    LEFT_DOUBLE_CLICK: 1,
  };

  const KeyboardEventModifier = {
    CTRL: 0,
  };

  const createWorldTerrainAsync = vi.fn(async () => ({ terrain: true }));
  const EllipsoidTerrainProvider = vi.fn(function (options?: unknown) {
    return { ellipsoidTerrain: true, options };
  });
  const Ion = { defaultAccessToken: '' };
  const GeographicTilingScheme = vi.fn(() => ({ kind: 'geographic' }));
  const TextureMinificationFilter = { LINEAR: 'linear', NEAREST: 'nearest' };
  const TextureMagnificationFilter = { LINEAR: 'linear', NEAREST: 'nearest' };

  class Ellipsoid {
    radii: { x: number; y: number; z: number };

    constructor(x = 1, y = 1, z = 1) {
      this.radii = { x, y, z };
    }
  }

  const baseEllipsoid = new Ellipsoid(10, 10, 9);

  let morphCompleteHandler: (() => void) | null = null;
  let leftClickHandler: ((movement: { position?: unknown }) => void) | null = null;
  let ctrlLeftClickHandler: ((movement: { position?: unknown }) => void) | null = null;
  let leftDoubleClickHandler: ((movement: { position?: unknown }) => void) | null = null;

  const Cartographic = {
    fromCartesian: vi.fn(() => ({ longitude: 0, latitude: 0 })),
  };

  const makeEvent = () => {
    const handlers = new Set<() => void>();
    return {
      addEventListener: vi.fn((handler: () => void) => {
        handlers.add(handler);
      }),
      removeEventListener: vi.fn((handler: () => void) => {
        handlers.delete(handler);
      }),
      __mocks: {
        trigger: () => {
          for (const handler of handlers) handler();
        },
      },
    };
  };

  const camera = {
    heading: 1,
    pitch: 0.5,
    roll: 0.1,
    position: { x: 1, y: 2, z: 3 },
    positionCartographic: { longitude: 0.1, latitude: 0.2, height: 123 },
    frustum: { near: 0.1, far: 1000 },
    computeViewRectangle: vi.fn(() => null),
    setView: vi.fn(),
    flyTo: vi.fn(),
    pickEllipsoid: vi.fn(() => ({ pickedEllipsoid: true })),
    changed: makeEvent(),
    moveEnd: makeEvent(),
  };

  const beforeExecute = {
    addEventListener: vi.fn(),
    removeEventListener: vi.fn()
  };

  const baseLayer = { baseLayer: true };

  const morphComplete = {
    addEventListener: vi.fn((handler: () => void) => {
      morphCompleteHandler = handler;
    }),
    removeEventListener: vi.fn()
  };

  const screenSpaceEventHandler = {
    setInputAction: vi.fn(
      (
        handler: (movement: { position?: unknown }) => void,
        type: unknown,
        modifier?: unknown,
      ) => {
        if (type === ScreenSpaceEventType.LEFT_CLICK && modifier === KeyboardEventModifier.CTRL) {
          ctrlLeftClickHandler = handler;
          return;
        }
        if (type === ScreenSpaceEventType.LEFT_DOUBLE_CLICK) {
          leftDoubleClickHandler = handler;
          return;
        }
        if (type === ScreenSpaceEventType.LEFT_CLICK) {
          leftClickHandler = handler;
        }
      },
    ),
    removeInputAction: vi.fn((type: unknown, modifier?: unknown) => {
      if (type === ScreenSpaceEventType.LEFT_CLICK && modifier === KeyboardEventModifier.CTRL) {
        ctrlLeftClickHandler = null;
        return;
      }
      if (type === ScreenSpaceEventType.LEFT_DOUBLE_CLICK) {
        leftDoubleClickHandler = null;
        return;
      }
      if (type === ScreenSpaceEventType.LEFT_CLICK) {
        leftClickHandler = null;
      }
    }),
  };

  const viewer = {
    camera,
    dataSources: {
      add: vi.fn(async (dataSource: unknown) => dataSource),
      remove: vi.fn(() => true),
    },
    entities: {
      add: vi.fn((entity: unknown) => entity),
      remove: vi.fn(() => true),
    },
    homeButton: {
      viewModel: {
        command: {
          beforeExecute
        }
      }
    },
    screenSpaceEventHandler,
	    imageryLayers: {
	      get: vi.fn(() => baseLayer),
	      remove: vi.fn(),
	      addImageryProvider: vi.fn(() => baseLayer),
	      add: vi.fn((layer: unknown) => layer),
	      raiseToTop: vi.fn(),
	    },
	    terrainProvider: { kind: 'base-terrain' },
	    scene: {
	      requestRenderMode: false,
	      maximumRenderTimeChange: 0,
	      requestRender: vi.fn(),
      mode: SceneMode.SCENE3D,
      morphComplete,
      morphTo2D: vi.fn(() => {
        viewer.scene.mode = SceneMode.SCENE2D;
      }),
      morphTo3D: vi.fn(() => {
        viewer.scene.mode = SceneMode.SCENE3D;
      }),
	      morphToColumbusView: vi.fn(() => {
	        viewer.scene.mode = SceneMode.COLUMBUS_VIEW;
	      }),
	      globe: {
	        ellipsoid: baseEllipsoid,
	      },
      fog: {
        enabled: false,
        density: 0,
        screenSpaceErrorFactor: 0,
        minimumBrightness: 0,
      },
      skyBox: { show: false },
      skyAtmosphere: { show: false },
      pick: vi.fn(() => null),
      pickPosition: vi.fn(() => ({ pickedPosition: true })),
      screenSpaceCameraController: {
        minimumZoomDistance: 0,
        maximumZoomDistance: 0,
        enableTilt: true,
        enableLook: true,
      },
      postRender: {
        addEventListener: vi.fn(),
        removeEventListener: vi.fn()
      },
      preUpdate: {
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      },
    },
    destroy: vi.fn()
  };

  return {
    SceneMode,
    ScreenSpaceEventType,
    KeyboardEventModifier,
    Cartographic,
    Color: {
      RED: { name: 'red', withAlpha: vi.fn((alpha: number) => ({ name: 'red', alpha })) },
      ORANGE: { name: 'orange', withAlpha: vi.fn((alpha: number) => ({ name: 'orange', alpha })) },
      YELLOW: { name: 'yellow', withAlpha: vi.fn((alpha: number) => ({ name: 'yellow', alpha })) },
      CYAN: { name: 'cyan', withAlpha: vi.fn((alpha: number) => ({ name: 'cyan', alpha })) },
      WHITE: { name: 'white', withAlpha: vi.fn((alpha: number) => ({ name: 'white', alpha })) },
      BLACK: { name: 'black', withAlpha: vi.fn((alpha: number) => ({ name: 'black', alpha })) },
    },
    Rectangle: {
      fromDegrees: vi.fn((west: number, south: number, east: number, north: number) => ({
        west,
        south,
        east,
        north,
      })),
    },
    PolygonHierarchy: vi.fn(function (positions: unknown[], holes?: unknown[]) {
      return { positions, holes: holes ?? [] };
    }),
    PolygonGraphics: vi.fn(function (options: unknown) {
      return { ...(options as Record<string, unknown>) };
    }),
    Entity: vi.fn(function (options: unknown) {
      return { ...(options as Record<string, unknown>) };
    }),
    CustomDataSource: vi.fn(function (name: string) {
      const instance = {
        name,
        entities: {
          add: vi.fn((entity: unknown) => entity),
          removeAll: vi.fn(),
        },
        clustering: {
          enabled: false,
          pixelRange: 0,
          minimumClusterSize: 2,
          clusterEvent: {
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
          },
        },
      };
      customDataSourceMocks.instances.push(instance);
      return instance;
    }),
    Viewer: vi.fn(function () {
      return viewer;
    }),
    ImageryLayer: vi.fn(function (provider: unknown, options?: unknown) {
      return {
        baseLayer: true,
        provider,
        ...(options && typeof options === 'object' ? (options as Record<string, unknown>) : {}),
      };
    }),
    Cartesian3: {
      fromDegrees: vi.fn(() => ({ destination: true })),
      fromRadians: vi.fn(() => ({ destinationRadians: true })),
      clone: vi.fn((value: unknown) => ({ ...(value as Record<string, unknown>), cloned: true }))
    },
    WebMapTileServiceImageryProvider: vi.fn(),
    UrlTemplateImageryProvider: vi.fn(function (options: unknown) {
      return { kind: 'url-template', options };
    }),
	    WebMercatorTilingScheme: vi.fn(),
	    GeographicTilingScheme,
	    TextureMinificationFilter,
	    TextureMagnificationFilter,
    Math: {
      toDegrees: vi.fn((radians: number) => radians),
      PI_OVER_TWO: Math.PI / 2
    },
    __mocks: {
      getMorphCompleteHandler: () => morphCompleteHandler,
      getCamera: () => camera,
      triggerLeftClick: (movement: { position?: unknown }) => {
        leftClickHandler?.(movement);
      },
      triggerCtrlLeftClick: (movement: { position?: unknown }) => {
        ctrlLeftClickHandler?.(movement);
      },
      triggerLeftDoubleClick: (movement: { position?: unknown }) => {
        leftDoubleClickHandler?.(movement);
      },
	    },
	    createWorldTerrainAsync,
	    Ellipsoid,
	    EllipsoidTerrainProvider,
	    Ion,
	  };
});

import { Cartesian3, EllipsoidTerrainProvider, Rectangle, createWorldTerrainAsync, Viewer } from 'cesium';
import { clearConfigCache } from '../../config';
import { DEFAULT_BASEMAP_ID } from '../../config/basemaps';
import { clearProductsCache } from '../products/productsApi';
import { clearCldasTileProbeCache } from '../layers/layersApi';
import { useBasemapStore } from '../../state/basemap';
import { DEFAULT_CAMERA_PERSPECTIVE_ID, useCameraPerspectiveStore } from '../../state/cameraPerspective';
import { useEventAutoLayersStore } from '../../state/eventAutoLayers';
import { DEFAULT_EVENT_LAYER_MODE, useEventLayersStore } from '../../state/eventLayers';
import { useLayerManagerStore } from '../../state/layerManager';
import { usePerformanceModeStore } from '../../state/performanceMode';
import { DEFAULT_SCENE_MODE_ID, useSceneModeStore } from '../../state/sceneMode';
import { useViewModeStore } from '../../state/viewMode';
import { CesiumViewer } from './CesiumViewer';

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

describe('CesiumViewer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    precipitationParticlesMocks.instances.length = 0;
    windArrowsMocks.instances.length = 0;
    customDataSourceMocks.instances.length = 0;
    clearConfigCache();
    clearProductsCache();
    clearCldasTileProbeCache();
    localStorage.removeItem('digital-earth.basemap');
    localStorage.removeItem('digital-earth.eventLayers');
    localStorage.removeItem('digital-earth.eventAutoLayers');
    localStorage.removeItem('digital-earth.sceneMode');
    localStorage.removeItem('digital-earth.layers');
    localStorage.removeItem('digital-earth.performanceMode');
    localStorage.removeItem('digital-earth.viewMode');
    localStorage.removeItem('digital-earth.cameraPerspective');
    useBasemapStore.setState({ basemapId: DEFAULT_BASEMAP_ID });
    useCameraPerspectiveStore.setState({ cameraPerspectiveId: DEFAULT_CAMERA_PERSPECTIVE_ID });
    useEventAutoLayersStore.setState({ restoreOnExit: true, overrides: {} });
    useEventLayersStore.setState({ enabled: false, mode: DEFAULT_EVENT_LAYER_MODE });
    useSceneModeStore.setState({ sceneModeId: DEFAULT_SCENE_MODE_ID });
    useLayerManagerStore.setState({ layers: [] });
    usePerformanceModeStore.setState({ enabled: false });
    useViewModeStore.setState({ route: { viewModeId: 'global' }, history: [], saved: {} });
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
        if (url.endsWith('/config.json')) {
          return jsonResponse({ apiBaseUrl: 'http://api.test' });
        }
        if (url === 'http://api.test/api/v1/products/1') {
          return jsonResponse({
            id: 1,
            title: '降雪',
            text: '降雪预警',
            issued_at: '2026-01-01T00:00:00Z',
            valid_from: '2026-01-01T00:00:00Z',
            valid_to: '2026-01-02T00:00:00Z',
            version: 1,
            status: 'published',
            hazards: [
              {
                id: 11,
                severity: 'high',
                geometry: {
                  type: 'Polygon',
                  coordinates: [
                    [
                      [126.0, 45.0],
                      [127.0, 45.0],
                      [127.0, 46.0],
                      [126.0, 46.0],
                      [126.0, 45.0],
                    ],
                  ],
                },
                bbox: { min_x: 126, min_y: 45, max_x: 127, max_y: 46 },
                valid_from: '2026-01-01T00:00:00Z',
                valid_to: '2026-01-02T00:00:00Z',
              },
            ],
          });
        }
        if (url === 'http://api.test/api/v1/products/2') {
          return jsonResponse({
            id: 2,
            title: 'rain',
            text: null,
            issued_at: '2026-01-01T00:00:00Z',
            valid_from: '2026-01-01T00:00:00Z',
            valid_to: '2026-01-02T00:00:00Z',
            version: 1,
            status: 'published',
            hazards: [],
          });
        }
        if (url.startsWith('http://api.test/api/v1/vectors/')) {
          return jsonResponse({
            vectors: [{ lon: 120, lat: 30, u: 1.5, v: -2 }],
          });
        }
        if (url.startsWith('http://api.test/api/v1/risk/pois')) {
          return jsonResponse({
            page: 1,
            page_size: 1000,
            total: 0,
            items: [],
          });
        }
        if (url === 'http://api.test/api/v1/risk/evaluate') {
          return jsonResponse({
            summary: {
              total: 0,
              duration_ms: 0,
              level_counts: {},
              reasons: {},
              max_level: null,
              avg_score: null,
            },
            results: [],
          });
        }
        return jsonResponse({});
      }),
    );
  });

  it('initializes and destroys Cesium Viewer', async () => {
    const { unmount } = render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0]?.value;
    expect(viewer).toBeTruthy();
    expect(screen.getByTestId('cesium-container')).toBeInTheDocument();

    unmount();
    expect(viewer.destroy).toHaveBeenCalledTimes(1);
  });

  it('sets default camera and zoom limits', async () => {
    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;

    expect(viewer.scene.requestRenderMode).toBe(true);
    expect(viewer.scene.maximumRenderTimeChange).toBe(Infinity);
    expect(viewer.camera.setView).toHaveBeenCalledWith({ destination: { destination: true } });

    expect(viewer.scene.screenSpaceCameraController.minimumZoomDistance).toBe(100);
    expect(viewer.scene.screenSpaceCameraController.maximumZoomDistance).toBe(40_000_000);
  });

  it('overrides home button to fly to default destination', async () => {
    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;
    const beforeExecute = viewer.homeButton.viewModel.command.beforeExecute;

    expect(beforeExecute.addEventListener).toHaveBeenCalledTimes(1);
    const handler = beforeExecute.addEventListener.mock.calls[0][0];
    const event = { cancel: false };
    handler(event);

    expect(event.cancel).toBe(true);
    expect(viewer.camera.flyTo).toHaveBeenCalledWith({
      destination: { destination: true },
      duration: 0.8
    });
  });

  it('compass button resets heading north-up', async () => {
    const user = userEvent.setup();
    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;

    await user.click(await screen.findByRole('button', { name: 'Compass' }));

    expect(viewer.camera.flyTo).toHaveBeenCalledWith(
      expect.objectContaining({
        destination: expect.objectContaining({ cloned: true }),
        orientation: {
          heading: 0,
          pitch: 0.5,
          roll: 0
        },
        duration: 0.3
      })
    );
  });

  it('switches basemap when selector changes', async () => {
    const user = userEvent.setup();
    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;
    const select = screen.getByRole('combobox', { name: '底图' });

    await user.selectOptions(select, 'nasa-gibs-blue-marble');

    await waitFor(() => {
      expect(viewer.imageryLayers.addImageryProvider).toHaveBeenCalledTimes(1);
    });

    expect(viewer.imageryLayers.get).toHaveBeenCalledWith(0);
    expect(viewer.imageryLayers.remove).toHaveBeenCalledWith(
      expect.objectContaining({ baseLayer: true }),
      true,
    );
    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(1);
  });

  it('hides basemap selector when basemapProvider is not open', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          apiBaseUrl: 'http://api.test',
          map: {
            basemapProvider: 'selfHosted',
            selfHosted: {
              basemapUrlTemplate: 'https://tiles.example/b/{z}/{x}/{y}.jpg',
              basemapScheme: 'xyz',
            },
          },
        }),
      ),
    );

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    await waitFor(() => {
      expect(screen.queryByRole('combobox', { name: '底图' })).toBeNull();
    });
  });

  it('falls back to ellipsoid terrain and shows a notice when ion token is missing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          apiBaseUrl: 'http://api.test',
          map: {
            terrainProvider: 'ion',
          },
        }),
      ),
    );

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;

    expect(await screen.findByRole('alert', { name: 'terrain-notice' })).toHaveTextContent(
      '未配置 Cesium ion token',
    );
    expect(vi.mocked(createWorldTerrainAsync)).not.toHaveBeenCalled();
    expect(vi.mocked(EllipsoidTerrainProvider)).toHaveBeenCalled();
    expect(viewer.scene.requestRender).toHaveBeenCalled();
  });

  it('falls back to ellipsoid terrain and shows a notice when ion terrain fails to load', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          apiBaseUrl: 'http://api.test',
          map: {
            terrainProvider: 'ion',
            cesiumIonAccessToken: 'token',
          },
        }),
      ),
    );

    vi.mocked(createWorldTerrainAsync).mockRejectedValueOnce(new Error('Terrain failed'));

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;

    expect(await screen.findByRole('alert', { name: 'terrain-notice' })).toHaveTextContent(
      '地形加载失败',
    );
    expect(vi.mocked(EllipsoidTerrainProvider)).toHaveBeenCalled();
    expect(viewer.scene.requestRender).toHaveBeenCalled();
  });

  it('switches scene mode and restores camera view after morph completes', async () => {
    const user = userEvent.setup();
    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const cesium = await import('cesium');
    const viewer = vi.mocked(Viewer).mock.results[0].value;

    await user.click(screen.getByRole('button', { name: '2D' }));

    await waitFor(() => expect(viewer.scene.morphTo2D).toHaveBeenCalledWith(0.8));

    const handler = (cesium as unknown as { __mocks: { getMorphCompleteHandler: () => (() => void) | null } })
      .__mocks.getMorphCompleteHandler();
    expect(handler).toBeTypeOf('function');

    handler?.();

    expect(viewer.camera.setView).toHaveBeenLastCalledWith({
      destination: { destinationRadians: true },
      orientation: {
        heading: 1,
        pitch: -(Math.PI / 2),
        roll: 0
      }
    });
    expect(viewer.scene.requestRender).toHaveBeenCalled();
  });

  it('syncs temperature imagery layers from layerManager and applies opacity/visibility', async () => {
    useLayerManagerStore.setState({
      layers: [
        {
          id: 'temperature',
          type: 'temperature',
          variable: 'TMP',
          opacity: 0.6,
          visible: true,
          zIndex: 10,
        },
      ],
    });

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;

    await waitFor(() => expect(viewer.imageryLayers.add).toHaveBeenCalledTimes(1));

    const imageryLayer = viewer.imageryLayers.add.mock.calls[0]?.[0] as {
      alpha?: number;
      show?: boolean;
    };

    expect(imageryLayer.alpha).toBe(0.6);
    expect(imageryLayer.show).toBe(true);
    expect(viewer.imageryLayers.raiseToTop).toHaveBeenCalledWith(imageryLayer);

    useLayerManagerStore.getState().setLayerOpacity('temperature', 0.3);
    await waitFor(() => expect(imageryLayer.alpha).toBe(0.3));

    useLayerManagerStore.getState().setLayerVisible('temperature', false);
    await waitFor(() => expect(imageryLayer.show).toBe(false));
  });

  it('orders temperature imagery layers by zIndex', async () => {
    useLayerManagerStore.setState({
      layers: [
        {
          id: 'temperature-low',
          type: 'temperature',
          variable: 'LOW',
          opacity: 1,
          visible: false,
          zIndex: 10,
        },
        {
          id: 'temperature-high',
          type: 'temperature',
          variable: 'HIGH',
          opacity: 1,
          visible: false,
          zIndex: 20,
        },
      ],
    });

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;

    await waitFor(() => expect(viewer.imageryLayers.raiseToTop).toHaveBeenCalledTimes(2));

    const raisedUrls = viewer.imageryLayers.raiseToTop.mock.calls.map(
      ([layer]: [unknown]) =>
        (layer as { provider?: { options?: { url?: string } } })?.provider?.options?.url ?? '',
    );

    expect(raisedUrls[0]).toContain('/LOW/');
    expect(raisedUrls[1]).toContain('/HIGH/');
  });

  it('syncs cloud imagery layers from layerManager and applies opacity/visibility', async () => {
    useLayerManagerStore.setState({
      layers: [
        {
          id: 'cloud',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.65,
          visible: true,
          zIndex: 20,
        },
      ],
    });

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;

    await waitFor(() => expect(viewer.imageryLayers.add).toHaveBeenCalledTimes(1));

    const imageryLayer = viewer.imageryLayers.add.mock.calls[0]?.[0] as {
      alpha?: number;
      show?: boolean;
    };

    expect(imageryLayer.alpha).toBe(0.65);
    expect(imageryLayer.show).toBe(true);
    expect(viewer.imageryLayers.raiseToTop).toHaveBeenCalledWith(imageryLayer);

    useLayerManagerStore.getState().setLayerOpacity('cloud', 0.3);
    await waitFor(() => expect(imageryLayer.alpha).toBe(0.3));

    useLayerManagerStore.getState().setLayerVisible('cloud', false);
    await waitFor(() => expect(imageryLayer.show).toBe(false));
  });

  it('syncs precipitation imagery layers from layerManager and applies threshold filtering', async () => {
    useLayerManagerStore.setState({
      layers: [
        {
          id: 'precipitation',
          type: 'precipitation',
          variable: 'precipitation',
          opacity: 0.9,
          visible: true,
          zIndex: 30,
          threshold: 1.5,
        },
      ],
    });

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;

    await waitFor(() => expect(viewer.imageryLayers.add).toHaveBeenCalledTimes(1));

    const imageryLayer = viewer.imageryLayers.add.mock.calls[0]?.[0] as {
      alpha?: number;
      show?: boolean;
      provider?: { options?: { url?: string } };
    };

    expect(imageryLayer.alpha).toBe(0.9);
    expect(imageryLayer.show).toBe(true);
    expect(imageryLayer.provider?.options?.url).toContain('/precipitation/');
    expect(imageryLayer.provider?.options?.url).toContain('threshold=1.5');
    expect(viewer.imageryLayers.raiseToTop).toHaveBeenCalledWith(imageryLayer);

    viewer.imageryLayers.remove.mockClear();

    useLayerManagerStore.getState().updateLayer('precipitation', { threshold: undefined });

    await waitFor(() => expect(viewer.imageryLayers.add).toHaveBeenCalledTimes(2));
    expect(viewer.imageryLayers.remove).toHaveBeenCalledWith(imageryLayer, true);
  });

  it('syncs snow depth imagery layers from layerManager and applies opacity/visibility', async () => {
    useLayerManagerStore.setState({
      layers: [
        {
          id: 'snow-depth',
          type: 'snow-depth',
          variable: 'SNOD',
          opacity: 0.55,
          visible: true,
          zIndex: 50,
        },
      ],
    });

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;

    await waitFor(() => expect(viewer.imageryLayers.add).toHaveBeenCalledTimes(1));

    const imageryLayer = viewer.imageryLayers.add.mock.calls[0]?.[0] as {
      alpha?: number;
      show?: boolean;
      provider?: { options?: { url?: string } };
    };

    expect(imageryLayer.alpha).toBe(0.55);
    expect(imageryLayer.show).toBe(true);
    expect(imageryLayer.provider?.options?.url).toContain('/SNOD/');
    expect(viewer.imageryLayers.raiseToTop).toHaveBeenCalledWith(imageryLayer);

    useLayerManagerStore.getState().setLayerOpacity('snow-depth', 0.25);
    await waitFor(() => expect(imageryLayer.alpha).toBe(0.25));

    useLayerManagerStore.getState().setLayerVisible('snow-depth', false);
    await waitFor(() => expect(imageryLayer.show).toBe(false));
  });

  it('orders imagery layers by zIndex across types', async () => {
    useLayerManagerStore.setState({
      layers: [
        {
          id: 'temperature-low',
          type: 'temperature',
          variable: 'LOW',
          opacity: 1,
          visible: false,
          zIndex: 10,
        },
        {
          id: 'cloud',
          type: 'cloud',
          variable: 'tcc',
          opacity: 1,
          visible: false,
          zIndex: 20,
        },
        {
          id: 'precipitation',
          type: 'precipitation',
          variable: 'precipitation',
          opacity: 1,
          visible: false,
          zIndex: 30,
        },
        {
          id: 'snow-depth',
          type: 'snow-depth',
          variable: 'SNOD',
          opacity: 1,
          visible: false,
          zIndex: 50,
        },
      ],
    });

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;

    await waitFor(() => expect(viewer.imageryLayers.raiseToTop).toHaveBeenCalledTimes(4));

    const raisedUrls = viewer.imageryLayers.raiseToTop.mock.calls.map(
      ([layer]: [unknown]) =>
        (layer as { provider?: { options?: { url?: string } } })?.provider?.options?.url ?? '',
    );

    expect(raisedUrls[0]).toContain('/LOW/');
    expect(raisedUrls[1]).toContain('/TCC/');
    expect(raisedUrls[2]).toContain('/precipitation/');
    expect(raisedUrls[3]).toContain('/SNOD/');
  });

  it('refreshes cloud tiles over time', async () => {
    const CLOUD_LAYER_REFRESH_INTERVAL_MS = 5 * 60 * 1000;
    let triggerRefresh: (() => void) | null = null;
    const setIntervalSpy = vi
      .spyOn(window, 'setInterval')
      .mockImplementation((handler: TimerHandler, timeout?: number, ...args: unknown[]) => {
        void args;
        if (timeout === CLOUD_LAYER_REFRESH_INTERVAL_MS && typeof handler === 'function') {
          triggerRefresh = handler as () => void;
        }
        return 1 as unknown as ReturnType<typeof window.setInterval>;
      });

    try {
      useLayerManagerStore.setState({
        layers: [
          {
            id: 'cloud',
            type: 'cloud',
            variable: 'tcc',
            opacity: 0.65,
            visible: true,
            zIndex: 20,
          },
        ],
      });

      render(<CesiumViewer />);

      await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

      const viewer = vi.mocked(Viewer).mock.results[0].value;

      await waitFor(() => expect(viewer.imageryLayers.add).toHaveBeenCalledTimes(1));

      await waitFor(() => expect(triggerRefresh).not.toBeNull());
      act(() => {
        triggerRefresh?.();
      });

      await waitFor(() => expect(viewer.imageryLayers.add).toHaveBeenCalledTimes(2));
      expect(viewer.imageryLayers.remove).toHaveBeenCalledTimes(1);
    } finally {
      setIntervalSpy.mockRestore();
    }
  });

  it('samples weather and updates precipitation particles when precipitation layer is visible', async () => {
    weatherSamplerMocks.sample.mockResolvedValueOnce({
      precipitationMm: 25,
      precipitationIntensity: 0.8,
      precipitationKind: 'rain',
      temperatureC: 10,
    });

    useLayerManagerStore.setState({
      layers: [
        {
          id: 'temperature',
          type: 'temperature',
          variable: 'TMP',
          opacity: 1,
          visible: true,
          zIndex: 10,
        },
        {
          id: 'precipitation',
          type: 'precipitation',
          variable: 'precipitation',
          opacity: 1,
          visible: true,
          zIndex: 30,
        },
      ],
    });

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    await waitFor(() => expect(weatherSamplerMocks.sample).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;
    expect(viewer.camera.changed.addEventListener).toHaveBeenCalled();

    expect(weatherSamplerMocks.sample).toHaveBeenCalledWith(
      expect.objectContaining({ lon: 0.1, lat: 0.2 }),
    );

    await waitFor(() => expect(precipitationParticlesMocks.update).toHaveBeenCalled());
    expect(precipitationParticlesMocks.update).toHaveBeenLastCalledWith(
      expect.objectContaining({
        enabled: true,
        intensity: 0.8,
        kind: 'rain',
        performanceModeEnabled: false,
      }),
    );
  });

  it('skips sampling and disables precipitation particles in performance mode', async () => {
    usePerformanceModeStore.setState({ enabled: true });

    useLayerManagerStore.setState({
      layers: [
        {
          id: 'temperature',
          type: 'temperature',
          variable: 'TMP',
          opacity: 1,
          visible: true,
          zIndex: 10,
        },
        {
          id: 'precipitation',
          type: 'precipitation',
          variable: 'precipitation',
          opacity: 1,
          visible: true,
          zIndex: 30,
        },
      ],
    });

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    await waitFor(() =>
      expect(precipitationParticlesMocks.update).toHaveBeenCalledWith(
        expect.objectContaining({
          enabled: false,
          kind: 'none',
          performanceModeEnabled: true,
        }),
      ),
    );

    expect(weatherSamplerMocks.sample).not.toHaveBeenCalled();
  });

  it('fetches wind vectors and updates wind arrows when wind layer is visible', async () => {
    useLayerManagerStore.setState({
      layers: [
        {
          id: 'wind',
          type: 'wind',
          variable: 'wind',
          opacity: 0.7,
          visible: true,
          zIndex: 15,
        },
      ],
    });

    const cesium = await import('cesium');
    (
      cesium as unknown as {
        __mocks: { getCamera: () => { computeViewRectangle: ReturnType<typeof vi.fn> } };
      }
    ).__mocks.getCamera().computeViewRectangle.mockReturnValue({
      west: 10,
      south: 20,
      east: 30,
      north: 40,
    });

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    await waitFor(() =>
      expect(windArrowsMocks.update).toHaveBeenCalledWith(
        expect.objectContaining({ enabled: true, opacity: 0.7 }),
      ),
    );

    const fetchMock = vi.mocked(globalThis.fetch);
    const windCall = fetchMock.mock.calls.find(
      ([url]) => typeof url === 'string' && url.includes('/api/v1/vectors/cldas/'),
    );
    expect(windCall?.[0]).toContain(
      'http://api.test/api/v1/vectors/cldas/2024-01-15T00%3A00%3A00Z/wind?bbox=10,20,30,40&density=12',
    );
  });

  it('opens sampling card and displays sampled values on map click', async () => {
    const user = userEvent.setup();

    weatherSamplerMocks.sample.mockResolvedValueOnce({
      precipitationMm: 12.3,
      precipitationIntensity: 0.1,
      precipitationKind: 'rain',
      temperatureC: 5,
    });
    cloudSamplerMocks.sample.mockResolvedValueOnce({ cloudCoverFraction: 0.33 });

    useLayerManagerStore.setState({
      layers: [
        {
          id: 'temperature',
          type: 'temperature',
          variable: 'TMP',
          opacity: 1,
          visible: true,
          zIndex: 10,
        },
        {
          id: 'precipitation',
          type: 'precipitation',
          variable: 'precipitation',
          opacity: 1,
          visible: false,
          zIndex: 30,
        },
        {
          id: 'cloud',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.65,
          visible: true,
          zIndex: 20,
        },
        {
          id: 'wind',
          type: 'wind',
          variable: 'wind',
          opacity: 0.7,
          visible: true,
          zIndex: 15,
        },
      ],
    });

    const cesium = await import('cesium');
    (
      cesium as unknown as {
        Cartographic: { fromCartesian: ReturnType<typeof vi.fn> };
        __mocks: { getCamera: () => { computeViewRectangle: ReturnType<typeof vi.fn> } };
      }
    ).Cartographic.fromCartesian.mockReturnValue({
      longitude: 120,
      latitude: 30,
    });
    (
      cesium as unknown as {
        __mocks: { getCamera: () => { computeViewRectangle: ReturnType<typeof vi.fn> } };
      }
    ).__mocks.getCamera().computeViewRectangle.mockReturnValue({
      west: 10,
      south: 20,
      east: 30,
      north: 40,
    });

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    await waitFor(() =>
      expect(windArrowsMocks.update).toHaveBeenCalledWith(
        expect.objectContaining({ enabled: true }),
      ),
    );

    act(() => {
      (
        cesium as unknown as {
          __mocks: { triggerLeftClick: (movement: { position?: unknown }) => void };
        }
      ).__mocks.triggerLeftClick({ position: { x: 12, y: 34 } });
    });

    const card = await screen.findByLabelText('Sampling data');
    const queries = within(card);

    await waitFor(() => expect(queries.getByText('5.0')).toBeInTheDocument());
    expect(queries.getByText('12.3')).toBeInTheDocument();
    expect(queries.getByText(/2\.5/)).toBeInTheDocument();
    expect(queries.getByText(/143°/)).toBeInTheDocument();
    expect(queries.getByText('33')).toBeInTheDocument();

    await user.click(queries.getByRole('button', { name: 'Close sampling card' }));
    await waitFor(() => expect(screen.queryByLabelText('Sampling data')).not.toBeInTheDocument());
  });

  it('enters local mode and flies camera on ctrl+click', async () => {
    useLayerManagerStore.setState({
      layers: [
        {
          id: 'cloud',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.8,
          visible: true,
          zIndex: 10,
        },
      ],
    });

    const cesium = await import('cesium');
    (
      cesium as unknown as {
        Cartographic: { fromCartesian: ReturnType<typeof vi.fn> };
      }
    ).Cartographic.fromCartesian.mockReturnValue({
      longitude: 120,
      latitude: 30,
      height: 100,
    });

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    act(() => {
      (
        cesium as unknown as {
          __mocks: { triggerCtrlLeftClick: (movement: { position?: unknown }) => void };
        }
      ).__mocks.triggerCtrlLeftClick({ position: { x: 12, y: 34 } });
    });

    await waitFor(() => expect(useViewModeStore.getState().route.viewModeId).toBe('local'));

    const viewer = vi.mocked(Viewer).mock.results[0].value;

    await waitFor(() => {
      expect(viewer.camera.flyTo).toHaveBeenCalledWith({
        destination: { destination: true },
        orientation: {
          heading: 1,
          pitch: -Math.PI / 4,
          roll: 0,
        },
        duration: 2.5,
      });
    });

    expect(viewer.scene.skyBox.show).toBe(true);
    expect(viewer.scene.skyAtmosphere.show).toBe(true);
    expect(viewer.scene.fog.enabled).toBe(true);
    expect(viewer.scene.fog.screenSpaceErrorFactor).toBe(3.0);
    expect(viewer.scene.fog.minimumBrightness).toBe(0.12);
    expect(viewer.scene.fog.density).toBeGreaterThan(0);
    expect(viewer.camera.frustum.near).toBe(0.2);
    expect(viewer.camera.frustum.far).toBe(50_000);

    const panel = await screen.findByLabelText('Local info');
    expect(panel).toHaveTextContent('30.0000, 120.0000');
    expect(panel).toHaveTextContent('100');
    expect(panel).toHaveTextContent('2024-01-15T00:00:00Z');
    expect(panel).toHaveTextContent('cloud:tcc');
  });

  it('applies camera perspective pitch and locks tilt in local mode', async () => {
    useViewModeStore.setState({
      route: { viewModeId: 'local', lat: 30, lon: 120, heightMeters: 100 },
      history: [],
      saved: {},
    });
    useCameraPerspectiveStore.setState({ cameraPerspectiveId: DEFAULT_CAMERA_PERSPECTIVE_ID });

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;

    await waitFor(() =>
      expect(viewer.camera.flyTo).toHaveBeenCalledWith(
        expect.objectContaining({
          duration: 2.5,
          orientation: expect.objectContaining({
            pitch: -Math.PI / 4,
          }),
        }),
      ),
    );

    expect(viewer.scene.screenSpaceCameraController.enableTilt).toBe(true);
    expect(viewer.scene.screenSpaceCameraController.enableLook).toBe(true);

    const callsBefore = viewer.camera.flyTo.mock.calls.length;

    act(() => {
      useCameraPerspectiveStore.getState().setCameraPerspectiveId('upward');
    });

    await waitFor(() => expect(viewer.camera.flyTo).toHaveBeenCalledTimes(callsBefore + 1));
    expect(viewer.scene.screenSpaceCameraController.enableTilt).toBe(false);
    expect(viewer.scene.screenSpaceCameraController.enableLook).toBe(false);
    expect(viewer.camera.flyTo).toHaveBeenLastCalledWith(
      expect.objectContaining({
        orientation: expect.objectContaining({
          pitch: Math.PI / 2 - Math.PI / 12,
        }),
        duration: 0.6,
      }),
    );

    act(() => {
      useCameraPerspectiveStore.getState().setCameraPerspectiveId('forward');
    });

    await waitFor(() => expect(viewer.camera.flyTo).toHaveBeenLastCalledWith(
      expect.objectContaining({
        orientation: expect.objectContaining({
          pitch: 0,
        }),
        duration: 0.6,
      }),
    ));

    const callsAfterForward = viewer.camera.flyTo.mock.calls.length;

    act(() => {
      useCameraPerspectiveStore.getState().setCameraPerspectiveId('free');
    });

    await waitFor(() => {
      expect(viewer.scene.screenSpaceCameraController.enableTilt).toBe(true);
      expect(viewer.scene.screenSpaceCameraController.enableLook).toBe(true);
    });
    expect(viewer.camera.flyTo).toHaveBeenCalledTimes(callsAfterForward);
  });

  it('flies camera above the shell and ensures the selected layer is visible in layerGlobal mode', async () => {
    useLayerManagerStore.setState({
      layers: [
        {
          id: 'cloud',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.8,
          visible: false,
          zIndex: 10,
        },
      ],
    });
    useViewModeStore.setState({
      route: { viewModeId: 'layerGlobal', layerId: 'cloud' },
      history: [],
      saved: {},
    });

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));
    const viewer = vi.mocked(Viewer).mock.results[0].value;

    await waitFor(() =>
      expect(viewer.camera.flyTo).toHaveBeenCalledWith({
        destination: { destination: true },
        orientation: {
          heading: 0,
          pitch: -Math.PI / 2,
          roll: 0,
        },
        duration: 2.0,
      }),
    );

    expect(vi.mocked(Cartesian3.fromDegrees)).toHaveBeenCalledWith(0, 0, 7500);

    await waitFor(() => {
      expect(useLayerManagerStore.getState().layers[0]?.visible).toBe(true);
    });

    await waitFor(() => {
      const radii = (
        viewer.scene.globe.ellipsoid as { radii?: { x?: number; y?: number; z?: number } }
      ).radii;
      expect(radii?.x).toBe(5010);
      expect(radii?.y).toBe(5010);
      expect(radii?.z).toBe(5009);
    });

    expect(vi.mocked(EllipsoidTerrainProvider)).toHaveBeenCalledWith(
      expect.objectContaining({
        ellipsoid: expect.objectContaining({
          radii: expect.objectContaining({ x: 5010, y: 5010, z: 5009 }),
        }),
      }),
    );
  });

  it.each(['2d', 'columbus'] as const)(
    'does not override the globe ellipsoid in %s scene mode',
    async (sceneModeId) => {
      useSceneModeStore.setState({ sceneModeId });
      useLayerManagerStore.setState({
        layers: [
          {
            id: 'cloud',
            type: 'cloud',
            variable: 'tcc',
            opacity: 0.8,
            visible: true,
            zIndex: 10,
          },
        ],
      });
      useViewModeStore.setState({
        route: { viewModeId: 'layerGlobal', layerId: 'cloud' },
        history: [],
        saved: {},
      });

      render(<CesiumViewer />);

      await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));
      const viewer = vi.mocked(Viewer).mock.results[0].value;

      await waitFor(() => {
        const radii = (
          viewer.scene.globe.ellipsoid as { radii?: { x?: number; y?: number; z?: number } }
        ).radii;
        expect(radii?.x).toBe(10);
        expect(radii?.y).toBe(10);
        expect(radii?.z).toBe(9);
      });

      expect(vi.mocked(EllipsoidTerrainProvider)).not.toHaveBeenCalled();
    },
  );

  it('restores the globe ellipsoid when leaving layerGlobal mode', async () => {
    useLayerManagerStore.setState({
      layers: [
        {
          id: 'cloud',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.8,
          visible: true,
          zIndex: 10,
        },
      ],
    });
    useViewModeStore.setState({
      route: { viewModeId: 'layerGlobal', layerId: 'cloud' },
      history: [],
      saved: {},
    });

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));
    const viewer = vi.mocked(Viewer).mock.results[0].value;

    await waitFor(() => {
      const radii = (
        viewer.scene.globe.ellipsoid as { radii?: { x?: number; y?: number; z?: number } }
      ).radii;
      expect(radii?.x).toBe(5010);
    });

    act(() => {
      useViewModeStore.setState({ route: { viewModeId: 'global' }, history: [], saved: {} });
    });

    await waitFor(() => {
      const radii = (
        viewer.scene.globe.ellipsoid as { radii?: { x?: number; y?: number; z?: number } }
      ).radii;
      expect(radii?.x).toBe(10);
      expect(radii?.y).toBe(10);
      expect(radii?.z).toBe(9);
    });
  });

  it('flies camera with fallback height when the selected layer is missing', async () => {
    useLayerManagerStore.setState({
      layers: [
        {
          id: 'temperature',
          type: 'temperature',
          variable: 'TMP',
          opacity: 0.8,
          visible: true,
          zIndex: 10,
        },
      ],
    });
    useViewModeStore.setState({
      route: { viewModeId: 'layerGlobal', layerId: 'missing-layer' },
      history: [],
      saved: {},
    });

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));
    const viewer = vi.mocked(Viewer).mock.results[0].value;

    await waitFor(() => {
      expect(viewer.camera.flyTo).toHaveBeenCalledWith(
        expect.objectContaining({
          destination: { destination: true },
          duration: 2.0,
        }),
      );
    });
    expect(vi.mocked(Cartesian3.fromDegrees)).toHaveBeenCalledWith(0, 0, 7500);
  });

  it('restores local layer/time state when returning from layerGlobal mode', async () => {
    let cloudTick: (() => void) | null = null;
    const setIntervalSpy = vi
      .spyOn(window, 'setInterval')
      .mockImplementation(((handler: TimerHandler) => {
        cloudTick = typeof handler === 'function' ? (handler as () => void) : null;
        return 1 as unknown as number;
      }) as typeof window.setInterval);

    const clearIntervalSpy = vi
      .spyOn(window, 'clearInterval')
      .mockImplementation(() => {});

    try {
      useLayerManagerStore.setState({
        layers: [
          {
            id: 'temperature',
            type: 'temperature',
            variable: 'TMP',
            opacity: 1,
            visible: true,
            zIndex: 10,
          },
          {
            id: 'cloud',
            type: 'cloud',
            variable: 'tcc',
            opacity: 0.65,
            visible: false,
            zIndex: 20,
          },
        ],
      });

      useViewModeStore.setState({
        route: { viewModeId: 'local', lat: 30, lon: 120, heightMeters: 0 },
        history: [],
        saved: {},
      });

      render(<CesiumViewer />);

      await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));
      const viewer = vi.mocked(Viewer).mock.results[0].value;

      const panelBefore = await screen.findByLabelText('Local info');
      expect(panelBefore).toHaveTextContent('temperature:TMP');
      expect(panelBefore).toHaveTextContent('2024-01-15T00:00:00Z');

      await waitFor(() => expect(setIntervalSpy).toHaveBeenCalled());
      act(() => {
        cloudTick?.();
      });

      act(() => {
        useViewModeStore.getState().enterLayerGlobal({ layerId: 'cloud' });
      });

      await waitFor(() => expect(useViewModeStore.getState().route.viewModeId).toBe('layerGlobal'));
      await waitFor(() => {
        expect(useLayerManagerStore.getState().layers.find((layer) => layer.id === 'cloud')?.visible).toBe(true);
      });

      const callsBeforeBack = viewer.camera.flyTo.mock.calls.length;

      act(() => {
        useViewModeStore.getState().goBack();
      });

      await waitFor(() => expect(useViewModeStore.getState().route.viewModeId).toBe('local'));
      await waitFor(() => {
        expect(useLayerManagerStore.getState().layers.find((layer) => layer.id === 'cloud')?.visible).toBe(false);
      });

      await waitFor(() => expect(viewer.camera.flyTo).toHaveBeenCalledTimes(callsBeforeBack + 1));
      expect(viewer.camera.flyTo).toHaveBeenLastCalledWith(
        expect.objectContaining({ duration: 1.2 }),
      );

      const panelAfter = await screen.findByLabelText('Local info');
      expect(panelAfter).toHaveTextContent('temperature:TMP');
      expect(panelAfter).toHaveTextContent('2024-01-15T00:00:00Z');
      expect(panelAfter).not.toHaveTextContent('2024-01-15T01:00:00Z');
    } finally {
      setIntervalSpy.mockRestore();
      clearIntervalSpy.mockRestore();
    }
  });

  it('does not restore local snapshot when entering local from layerGlobal (forward transition)', async () => {
    useLayerManagerStore.setState({
      layers: [
        {
          id: 'cloud',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.8,
          visible: true,
          zIndex: 10,
        },
      ],
    });
    useViewModeStore.setState({
      route: { viewModeId: 'local', lat: 30, lon: 120, heightMeters: 0 },
      history: [],
      saved: {},
    });

    const cesium = await import('cesium');
    (
      cesium as unknown as {
        Cartographic: { fromCartesian: ReturnType<typeof vi.fn> };
      }
    ).Cartographic.fromCartesian.mockReturnValue({
      longitude: 110,
      latitude: 35,
      height: 200,
    });

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));
    const viewer = vi.mocked(Viewer).mock.results[0].value;

    act(() => {
      useViewModeStore.getState().enterLayerGlobal({ layerId: 'cloud' });
    });

    await waitFor(() => expect(useViewModeStore.getState().route.viewModeId).toBe('layerGlobal'));

    const callsBeforeEnterLocal = viewer.camera.flyTo.mock.calls.length;

    act(() => {
      (
        cesium as unknown as {
          __mocks: { triggerCtrlLeftClick: (movement: { position?: unknown }) => void };
        }
      ).__mocks.triggerCtrlLeftClick({ position: { x: 12, y: 34 } });
    });

    await waitFor(() => expect(useViewModeStore.getState().route.viewModeId).toBe('local'));
    await waitFor(() =>
      expect(viewer.camera.flyTo).toHaveBeenCalledTimes(callsBeforeEnterLocal + 1),
    );

    expect(viewer.camera.flyTo).toHaveBeenLastCalledWith(
      expect.objectContaining({ duration: 2.5 }),
    );
  });

  it('caches wind vector requests for repeated view keys', async () => {
    const nowSpy = vi.spyOn(Date, 'now');
    let now = 0;
    nowSpy.mockImplementation(() => (now += 1000));

    try {
      useLayerManagerStore.setState({
        layers: [
          {
            id: 'wind',
            type: 'wind',
            variable: 'wind',
            opacity: 0.7,
            visible: true,
            zIndex: 10,
          },
        ],
      });

      const cesium = await import('cesium');
      (
        cesium as unknown as {
          __mocks: { getCamera: () => { computeViewRectangle: ReturnType<typeof vi.fn> } };
        }
      ).__mocks.getCamera().computeViewRectangle.mockReturnValue({
        west: 10,
        south: 20,
        east: 30,
        north: 40,
      });

      render(<CesiumViewer />);

      await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));
      const viewer = vi.mocked(Viewer).mock.results[0].value;

      await waitFor(() => expect(windArrowsMocks.update).toHaveBeenCalled());

      const fetchMock = vi.mocked(globalThis.fetch);
      const windCallsAfterFirst = fetchMock.mock.calls.filter(
        ([url]) => typeof url === 'string' && url.includes('/api/v1/vectors/cldas/'),
      ).length;
      expect(windCallsAfterFirst).toBe(1);

      (
        cesium as unknown as {
          __mocks: { getCamera: () => { computeViewRectangle: ReturnType<typeof vi.fn> } };
        }
      ).__mocks.getCamera().computeViewRectangle.mockReturnValue({
        west: 1,
        south: 2,
        east: 3,
        north: 4,
      });

      act(() => {
        (
          viewer.camera.changed as unknown as { __mocks?: { trigger: () => void } }
        ).__mocks?.trigger();
      });

      await waitFor(() => {
        const calls = fetchMock.mock.calls.filter(
          ([url]) => typeof url === 'string' && url.includes('/api/v1/vectors/cldas/'),
        ).length;
        expect(calls).toBe(2);
      });

      (
        cesium as unknown as {
          __mocks: { getCamera: () => { computeViewRectangle: ReturnType<typeof vi.fn> } };
        }
      ).__mocks.getCamera().computeViewRectangle.mockReturnValue({
        west: 10,
        south: 20,
        east: 30,
        north: 40,
      });

      const callsBeforeCacheHit = fetchMock.mock.calls.filter(
        ([url]) => typeof url === 'string' && url.includes('/api/v1/vectors/cldas/'),
      ).length;
      const updateCallsBeforeCacheHit = windArrowsMocks.update.mock.calls.length;

      act(() => {
        (
          viewer.camera.changed as unknown as { __mocks?: { trigger: () => void } }
        ).__mocks?.trigger();
      });

      await waitFor(() =>
        expect(windArrowsMocks.update).toHaveBeenCalledTimes(updateCallsBeforeCacheHit + 1),
      );

      const callsAfterCacheHit = fetchMock.mock.calls.filter(
        ([url]) => typeof url === 'string' && url.includes('/api/v1/vectors/cldas/'),
      ).length;
      expect(callsAfterCacheHit).toBe(callsBeforeCacheHit);
    } finally {
      nowSpy.mockRestore();
    }
  });

  it('cancels in-flight wind requests when serving cached vectors', async () => {
    const nowSpy = vi.spyOn(Date, 'now');
    let now = 0;
    nowSpy.mockImplementation(() => (now += 1000));

    const vectorsA = [{ lon: 10, lat: 20, u: 1, v: 2 }];
    const vectorsB = [{ lon: 99, lat: 88, u: -3, v: 4 }];

    let resolveSecondFetch:
      | ((response: { ok: boolean; json: () => Promise<unknown> }) => void)
      | null = null;
    let secondSignal: AbortSignal | undefined;
    let secondAborted = false;
    let resolveSecondJson: (() => void) | null = null;
    const secondJsonRead = new Promise<void>((resolve) => {
      resolveSecondJson = resolve;
    });

    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url =
          typeof input === 'string'
            ? input
            : input instanceof URL
              ? input.toString()
              : input.url;
        if (url.endsWith('/config.json')) {
          return Promise.resolve(jsonResponse({ apiBaseUrl: 'http://api.test' }));
        }
        if (url.startsWith('http://api.test/api/v1/vectors/')) {
          if (url.includes('bbox=10,20,30,40')) {
            return Promise.resolve(jsonResponse({ vectors: vectorsA }));
	          }
	          if (url.includes('bbox=1,2,3,4')) {
	            secondSignal = init?.signal ?? undefined;
	            if (secondSignal) {
	              secondAborted = secondSignal.aborted;
	              secondSignal.addEventListener('abort', () => {
	                secondAborted = true;
	              });
            }
            return new Promise((resolve) => {
              resolveSecondFetch = resolve;
            });
          }
          return Promise.resolve(jsonResponse({ vectors: [] }));
        }
        return Promise.resolve(jsonResponse({}));
      }),
    );

    try {
      useLayerManagerStore.setState({
        layers: [
          {
            id: 'wind',
            type: 'wind',
            variable: 'wind',
            opacity: 0.7,
            visible: true,
            zIndex: 10,
          },
        ],
      });

      const cesium = await import('cesium');
      (
        cesium as unknown as {
          __mocks: { getCamera: () => { computeViewRectangle: ReturnType<typeof vi.fn> } };
        }
      ).__mocks.getCamera().computeViewRectangle.mockReturnValue({
        west: 10,
        south: 20,
        east: 30,
        north: 40,
      });

      render(<CesiumViewer />);

      await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));
      const viewer = vi.mocked(Viewer).mock.results[0].value;

      await waitFor(() =>
        expect(windArrowsMocks.update).toHaveBeenCalledWith(
          expect.objectContaining({
            enabled: true,
            vectors: vectorsA,
          }),
        ),
      );

      (
        cesium as unknown as {
          __mocks: { getCamera: () => { computeViewRectangle: ReturnType<typeof vi.fn> } };
        }
      ).__mocks.getCamera().computeViewRectangle.mockReturnValue({
        west: 1,
        south: 2,
        east: 3,
        north: 4,
      });

      act(() => {
        (
          viewer.camera.changed as unknown as { __mocks?: { trigger: () => void } }
        ).__mocks?.trigger();
      });

      await waitFor(() => expect(resolveSecondFetch).not.toBeNull());
      expect(secondSignal).toBeTruthy();

      (
        cesium as unknown as {
          __mocks: { getCamera: () => { computeViewRectangle: ReturnType<typeof vi.fn> } };
        }
      ).__mocks.getCamera().computeViewRectangle.mockReturnValue({
        west: 10,
        south: 20,
        east: 30,
        north: 40,
      });

      act(() => {
        (
          viewer.camera.changed as unknown as { __mocks?: { trigger: () => void } }
        ).__mocks?.trigger();
      });

      await waitFor(() => expect(secondAborted).toBe(true));
      expect(secondSignal?.aborted).toBe(true);

      act(() => {
        resolveSecondFetch?.({
          ok: true,
          json: async () => {
            resolveSecondJson?.();
            return { vectors: vectorsB };
          },
        });
      });

      await secondJsonRead;
      await Promise.resolve();

      expect(windArrowsMocks.update).toHaveBeenLastCalledWith(
        expect.objectContaining({
          vectors: vectorsA,
        }),
      );
    } finally {
      nowSpy.mockRestore();
    }
  });

  it('applies the snow event layer template when entering event mode', async () => {
    useLayerManagerStore.setState({
      layers: [
        {
          id: 'temperature',
          type: 'temperature',
          variable: 'TMP',
          opacity: 1,
          visible: false,
          zIndex: 10,
        },
        {
          id: 'cloud',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.65,
          visible: false,
          zIndex: 20,
        },
        {
          id: 'precipitation',
          type: 'precipitation',
          variable: 'precipitation',
          opacity: 0.9,
          visible: false,
          zIndex: 30,
        },
        {
          id: 'wind',
          type: 'wind',
          variable: 'wind',
          opacity: 0.9,
          visible: true,
          zIndex: 40,
        },
        {
          id: 'snow-depth',
          type: 'snow-depth',
          variable: 'SNOD',
          opacity: 0.75,
          visible: false,
          zIndex: 50,
        },
      ],
    });

    render(<CesiumViewer />);
    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    act(() => {
      useViewModeStore.getState().enterEvent({ productId: '1' });
    });

    await waitFor(() => {
      const visible = useLayerManagerStore.getState().getVisibleLayers().map((layer) => layer.id);
      expect([...visible].sort()).toEqual(['cloud', 'precipitation', 'snow-depth', 'temperature']);
    });

    expect(useLayerManagerStore.getState().layers.find((layer) => layer.id === 'wind')?.visible).toBe(false);
  });

  it('applies user overrides for event auto layers when entering event mode', async () => {
    useEventAutoLayersStore.getState().setOverride('snow', ['wind', 'cloud']);

    useLayerManagerStore.setState({
      layers: [
        {
          id: 'temperature',
          type: 'temperature',
          variable: 'TMP',
          opacity: 1,
          visible: false,
          zIndex: 10,
        },
        {
          id: 'cloud',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.65,
          visible: false,
          zIndex: 20,
        },
        {
          id: 'precipitation',
          type: 'precipitation',
          variable: 'precipitation',
          opacity: 0.9,
          visible: false,
          zIndex: 30,
        },
        {
          id: 'wind',
          type: 'wind',
          variable: 'wind',
          opacity: 0.9,
          visible: true,
          zIndex: 40,
        },
        {
          id: 'snow-depth',
          type: 'snow-depth',
          variable: 'SNOD',
          opacity: 0.75,
          visible: false,
          zIndex: 50,
        },
      ],
    });

    render(<CesiumViewer />);
    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    act(() => {
      useViewModeStore.getState().enterEvent({ productId: '1' });
    });

    await waitFor(() => {
      const visible = useLayerManagerStore.getState().getVisibleLayers().map((layer) => layer.id);
      expect([...visible].sort()).toEqual(['cloud', 'wind']);
    });

    expect(
      useLayerManagerStore.getState().layers.find((layer) => layer.id === 'precipitation')?.visible,
    ).toBe(false);
    expect(useLayerManagerStore.getState().layers.find((layer) => layer.id === 'temperature')?.visible).toBe(
      false,
    );
    expect(useLayerManagerStore.getState().layers.find((layer) => layer.id === 'snow-depth')?.visible).toBe(
      false,
    );
  });

  it('retries applying the event layer template when layers load after entering event mode', async () => {
    useLayerManagerStore.setState({
      layers: [
        {
          id: 'wind',
          type: 'wind',
          variable: 'wind',
          opacity: 0.9,
          visible: true,
          zIndex: 40,
        },
      ],
    });

    render(<CesiumViewer />);
    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;

    act(() => {
      useViewModeStore.getState().enterEvent({ productId: '1' });
    });

    await waitFor(() => expect(viewer.entities.add).toHaveBeenCalled());

    act(() => {
      useLayerManagerStore.setState({
        layers: [
          {
            id: 'temperature',
            type: 'temperature',
            variable: 'TMP',
            opacity: 1,
            visible: false,
            zIndex: 10,
          },
          {
            id: 'cloud',
            type: 'cloud',
            variable: 'tcc',
            opacity: 0.65,
            visible: false,
            zIndex: 20,
          },
          {
            id: 'precipitation',
            type: 'precipitation',
            variable: 'precipitation',
            opacity: 0.9,
            visible: false,
            zIndex: 30,
          },
          {
            id: 'wind',
            type: 'wind',
            variable: 'wind',
            opacity: 0.9,
            visible: true,
            zIndex: 40,
          },
          {
            id: 'snow-depth',
            type: 'snow-depth',
            variable: 'SNOD',
            opacity: 0.75,
            visible: false,
            zIndex: 50,
          },
        ],
      });
    });

    await waitFor(() => {
      const visible = useLayerManagerStore.getState().getVisibleLayers().map((layer) => layer.id);
      expect([...visible].sort()).toEqual(['cloud', 'precipitation', 'snow-depth', 'temperature']);
    });

    expect(useLayerManagerStore.getState().layers.find((layer) => layer.id === 'wind')?.visible).toBe(false);
  });

  it('re-evaluates event auto layers when switching productId in event mode', async () => {
    useEventAutoLayersStore.getState().setOverride('rain', ['wind']);

    useLayerManagerStore.setState({
      layers: [
        {
          id: 'temperature',
          type: 'temperature',
          variable: 'TMP',
          opacity: 1,
          visible: false,
          zIndex: 10,
        },
        {
          id: 'cloud',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.65,
          visible: false,
          zIndex: 20,
        },
        {
          id: 'precipitation',
          type: 'precipitation',
          variable: 'precipitation',
          opacity: 0.9,
          visible: false,
          zIndex: 30,
        },
        {
          id: 'wind',
          type: 'wind',
          variable: 'wind',
          opacity: 0.9,
          visible: true,
          zIndex: 40,
        },
        {
          id: 'snow-depth',
          type: 'snow-depth',
          variable: 'SNOD',
          opacity: 0.75,
          visible: false,
          zIndex: 50,
        },
      ],
    });

    render(<CesiumViewer />);
    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    act(() => {
      useViewModeStore.getState().enterEvent({ productId: '1' });
    });

    await waitFor(() => {
      const visible = useLayerManagerStore.getState().getVisibleLayers().map((layer) => layer.id);
      expect([...visible].sort()).toEqual(['cloud', 'precipitation', 'snow-depth', 'temperature']);
    });

    act(() => {
      useViewModeStore.getState().enterEvent({ productId: '2' });
    });

    await waitFor(() => {
      const visible = useLayerManagerStore.getState().getVisibleLayers().map((layer) => layer.id);
      expect(visible).toEqual(['wind']);
    });
  });

  it('restores the pre-event layer state when exiting event mode', async () => {
    useLayerManagerStore.setState({
      layers: [
        {
          id: 'temperature',
          type: 'temperature',
          variable: 'TMP',
          opacity: 1,
          visible: false,
          zIndex: 10,
        },
        {
          id: 'cloud',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.65,
          visible: false,
          zIndex: 20,
        },
        {
          id: 'precipitation',
          type: 'precipitation',
          variable: 'precipitation',
          opacity: 0.9,
          visible: false,
          zIndex: 30,
        },
        {
          id: 'wind',
          type: 'wind',
          variable: 'wind',
          opacity: 0.9,
          visible: true,
          zIndex: 40,
        },
      ],
    });

    render(<CesiumViewer />);
    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    act(() => {
      useViewModeStore.getState().enterEvent({ productId: '1' });
    });

    await waitFor(() => {
      const visible = useLayerManagerStore.getState().getVisibleLayers().map((layer) => layer.id);
      expect([...visible].sort()).toEqual(['cloud', 'precipitation', 'temperature']);
    });

    act(() => {
      useViewModeStore.getState().enterGlobal();
    });

    await waitFor(() => {
      expect(useLayerManagerStore.getState().getVisibleLayers().map((layer) => layer.id)).toEqual(['wind']);
    });
  });

  it('keeps event layers when restoreOnExit is disabled', async () => {
    useEventAutoLayersStore.setState({ restoreOnExit: false, overrides: {} });
    useLayerManagerStore.setState({
      layers: [
        {
          id: 'temperature',
          type: 'temperature',
          variable: 'TMP',
          opacity: 1,
          visible: false,
          zIndex: 10,
        },
        {
          id: 'cloud',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.65,
          visible: false,
          zIndex: 20,
        },
        {
          id: 'precipitation',
          type: 'precipitation',
          variable: 'precipitation',
          opacity: 0.9,
          visible: false,
          zIndex: 30,
        },
        {
          id: 'wind',
          type: 'wind',
          variable: 'wind',
          opacity: 0.9,
          visible: true,
          zIndex: 40,
        },
      ],
    });

    render(<CesiumViewer />);
    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    act(() => {
      useViewModeStore.getState().enterEvent({ productId: '1' });
    });

    await waitFor(() => {
      const visible = useLayerManagerStore.getState().getVisibleLayers().map((layer) => layer.id);
      expect([...visible].sort()).toEqual(['cloud', 'precipitation', 'temperature']);
    });

    act(() => {
      useViewModeStore.getState().enterGlobal();
    });

    await waitFor(() => {
      const visible = useLayerManagerStore.getState().getVisibleLayers().map((layer) => layer.id);
      expect([...visible].sort()).toEqual(['cloud', 'precipitation', 'temperature']);
    });
  });

  it('plots event polygon and flies camera when entering event mode', async () => {
    render(<CesiumViewer />);
    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;
    vi.mocked(viewer.camera.flyTo).mockClear();
    vi.mocked(viewer.entities.add).mockClear();
    vi.mocked(Rectangle.fromDegrees).mockClear();

    act(() => {
      useViewModeStore.getState().enterEvent({ productId: '1' });
    });

    await waitFor(() => expect(viewer.entities.add).toHaveBeenCalled());

    expect(Rectangle.fromDegrees).toHaveBeenCalledWith(126, 45, 127, 46);
    expect(viewer.camera.flyTo).toHaveBeenCalledWith(
      expect.objectContaining({ duration: 1.8 }),
    );

    const [entity] = vi.mocked(viewer.entities.add).mock.calls[0] ?? [];
    expect(entity).toMatchObject({
      id: 'event:1:11:0',
      polygon: expect.objectContaining({
        outline: true,
        outlineWidth: 2,
      }),
    });
  });

  it('loads and renders risk POIs with clustering in event mode', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url =
          typeof input === 'string'
            ? input
            : input instanceof URL
              ? input.toString()
              : input.url;
        if (url.endsWith('/config.json')) {
          return jsonResponse({ apiBaseUrl: 'http://api.test' });
        }
        if (url === 'http://api.test/api/v1/products/1') {
          return jsonResponse({
            id: 1,
            title: '降雪',
            text: '降雪预警',
            issued_at: '2026-01-01T00:00:00Z',
            valid_from: '2026-01-01T00:00:00Z',
            valid_to: '2026-01-02T00:00:00Z',
            version: 1,
            status: 'published',
            hazards: [
              {
                id: 11,
                severity: 'high',
                geometry: null,
                bbox: { min_x: 126, min_y: 45, max_x: 127, max_y: 46 },
                valid_from: '2026-01-01T00:00:00Z',
                valid_to: '2026-01-02T00:00:00Z',
              },
            ],
          });
        }
        if (url.startsWith('http://api.test/api/v1/risk/pois')) {
          return jsonResponse({
            page: 1,
            page_size: 1000,
            total: 1,
            items: [
              {
                id: 101,
                name: 'poi-a',
                type: 'fire',
                lon: 126.5,
                lat: 45.5,
                alt: null,
                weight: 1,
                tags: null,
                risk_level: null,
              },
            ],
          });
        }
        if (url === 'http://api.test/api/v1/risk/evaluate') {
          expect(init?.method).toBe('POST');
          return jsonResponse({
            summary: {
              total: 1,
              duration_ms: 1,
              level_counts: { '4': 1 },
              reasons: {},
              max_level: 4,
              avg_score: 0.9,
            },
            results: [
              {
                poi_id: 101,
                level: 4,
                score: 0.9,
                factors: [],
                reasons: [],
              },
            ],
          });
        }
        return jsonResponse({});
      }),
    );

    const cesium = await import('cesium');
    render(<CesiumViewer />);
    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    act(() => {
      useViewModeStore.getState().enterEvent({ productId: '1' });
    });

    await waitFor(() => expect(customDataSourceMocks.instances.length).toBe(1));
    const [dataSource] = customDataSourceMocks.instances;
    await waitFor(() => expect(dataSource?.entities.add).toHaveBeenCalled());

    await waitFor(() => {
      const entities = vi
        .mocked(dataSource!.entities.add)
        .mock.calls.map((call) => call[0])
        .filter(Boolean);
      expect(entities.some((entity) => (entity as { label?: { text?: string } }).label?.text === '4')).toBe(
        true,
      );
    });

    const entity = vi
      .mocked(dataSource!.entities.add)
      .mock.calls.map((call) => call[0])
      .find((item) => (item as { label?: { text?: string } }).label?.text === '4');
    expect(entity).toMatchObject({
      id: 'risk-poi:101',
      label: expect.objectContaining({ text: '4' }),
      point: expect.objectContaining({
        color: { name: 'red', alpha: 0.85 },
        outlineColor: { name: 'white', alpha: 0.9 },
      }),
    });

    const camera = (cesium as unknown as { __mocks: { getCamera: () => { positionCartographic: { height: number }; changed: { __mocks: { trigger: () => void } } } } }).__mocks.getCamera();
    expect(dataSource!.clustering.enabled).toBe(false);
    camera.positionCartographic.height = 900_000;
    camera.changed.__mocks.trigger();
    expect(dataSource!.clustering.enabled).toBe(true);
    expect(dataSource!.clustering.pixelRange).toBe(60);
  });

  it('renders risk POIs even when risk evaluation fails', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
      if (url.endsWith('/config.json')) {
        return jsonResponse({ apiBaseUrl: 'http://api.test' });
      }
      if (url === 'http://api.test/api/v1/products/1') {
        return jsonResponse({
          id: 1,
          title: '降雪',
          text: '降雪预警',
          issued_at: '2026-01-01T00:00:00Z',
          valid_from: '2026-01-01T00:00:00Z',
          valid_to: '2026-01-02T00:00:00Z',
          version: 1,
          status: 'published',
          hazards: [
            {
              id: 11,
              severity: 'high',
              geometry: null,
              bbox: { min_x: 126, min_y: 45, max_x: 127, max_y: 46 },
              valid_from: '2026-01-01T00:00:00Z',
              valid_to: '2026-01-02T00:00:00Z',
            },
          ],
        });
      }
      if (url.startsWith('http://api.test/api/v1/risk/pois')) {
        return jsonResponse({
          page: 1,
          page_size: 1000,
          total: 1,
          items: [
            {
              id: 101,
              name: 'poi-a',
              type: 'fire',
              lon: 126.5,
              lat: 45.5,
              alt: null,
              weight: 1,
              tags: null,
              risk_level: 3,
            },
          ],
        });
      }
      if (url === 'http://api.test/api/v1/risk/evaluate') {
        return new Response('Internal Server Error', { status: 500 });
      }
      return jsonResponse({});
    });

    vi.stubGlobal('fetch', fetchMock);

    render(<CesiumViewer />);
    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    act(() => {
      useViewModeStore.getState().enterEvent({ productId: '1' });
    });

    await waitFor(() => expect(customDataSourceMocks.instances.length).toBe(1));
    const [dataSource] = customDataSourceMocks.instances;
    await waitFor(() => expect(dataSource?.entities.add).toHaveBeenCalled());

    const entity = vi
      .mocked(dataSource!.entities.add)
      .mock.calls.map((call) => call[0])
      .find((item) => (item as { id?: string }).id === 'risk-poi:101');
    expect(entity).toMatchObject({
      id: 'risk-poi:101',
      label: expect.objectContaining({ text: '3' }),
    });

    expect(warnSpy).toHaveBeenCalledWith(
      '[Digital Earth] failed to evaluate risk levels',
      expect.anything(),
    );
    warnSpy.mockRestore();
  });

  it('posts risk evaluation using bbox instead of all poi ids', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
      if (url.endsWith('/config.json')) {
        return jsonResponse({ apiBaseUrl: 'http://api.test' });
      }
      if (url === 'http://api.test/api/v1/products/1') {
        return jsonResponse({
          id: 1,
          title: '降雪',
          text: '降雪预警',
          issued_at: '2026-01-01T00:00:00Z',
          valid_from: '2026-01-01T00:00:00Z',
          valid_to: '2026-01-02T00:00:00Z',
          version: 1,
          status: 'published',
          hazards: [
            {
              id: 11,
              severity: 'high',
              geometry: null,
              bbox: { min_x: 126, min_y: 45, max_x: 127, max_y: 46 },
              valid_from: '2026-01-01T00:00:00Z',
              valid_to: '2026-01-02T00:00:00Z',
            },
          ],
        });
      }
      if (url.startsWith('http://api.test/api/v1/risk/pois')) {
        return jsonResponse({
          page: 1,
          page_size: 1000,
          total: 1,
          items: [
            {
              id: 101,
              name: 'poi-a',
              type: 'fire',
              lon: 126.5,
              lat: 45.5,
              alt: null,
              weight: 1,
              tags: null,
              risk_level: null,
            },
          ],
        });
      }
      if (url === 'http://api.test/api/v1/risk/evaluate') {
        const body = JSON.parse(String(init?.body ?? '')) as { bbox?: unknown; poi_ids?: unknown };
        expect(body.poi_ids).toBeUndefined();
        expect(body.bbox).toEqual([126, 45, 127, 46]);
        return jsonResponse({
          summary: {
            total: 1,
            duration_ms: 1,
            level_counts: {},
            reasons: {},
            max_level: null,
            avg_score: null,
          },
          results: [],
        });
      }
      return jsonResponse({});
    });

    vi.stubGlobal('fetch', fetchMock);

    render(<CesiumViewer />);
    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    act(() => {
      useViewModeStore.getState().enterEvent({ productId: '1' });
    });

    await waitFor(() => {
      const didEvaluate = fetchMock.mock.calls.some((call) => {
        const url = typeof call[0] === 'string' ? call[0] : (call[0] as URL).toString();
        return url === 'http://api.test/api/v1/risk/evaluate';
      });
      expect(didEvaluate).toBe(true);
    });
  });

  it('tears down risk clustering when unmounting in event mode', async () => {
    const { unmount } = render(<CesiumViewer />);
    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));
    const viewer = vi.mocked(Viewer).mock.results[0].value;

    act(() => {
      useViewModeStore.getState().enterEvent({ productId: '1' });
    });

    await waitFor(() => expect(customDataSourceMocks.instances.length).toBe(1));
    const [dataSource] = customDataSourceMocks.instances;

    expect(viewer.camera.changed.addEventListener).toHaveBeenCalled();
    expect(viewer.camera.moveEnd.addEventListener).toHaveBeenCalled();

    unmount();

    expect(viewer.camera.changed.removeEventListener).toHaveBeenCalled();
    expect(viewer.camera.moveEnd.removeEventListener).toHaveBeenCalled();
    expect(dataSource.clustering.clusterEvent.removeEventListener).toHaveBeenCalled();
  });

  it('opens a risk POI popup on click and can jump to disaster demo', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url =
          typeof input === 'string'
            ? input
            : input instanceof URL
              ? input.toString()
              : input.url;
        if (url.endsWith('/config.json')) {
          return jsonResponse({ apiBaseUrl: 'http://api.test' });
        }
        if (url === 'http://api.test/api/v1/products/1') {
          return jsonResponse({
            id: 1,
            title: '降雪',
            text: '降雪预警',
            issued_at: '2026-01-01T00:00:00Z',
            valid_from: '2026-01-01T00:00:00Z',
            valid_to: '2026-01-02T00:00:00Z',
            version: 1,
            status: 'published',
            hazards: [
              {
                id: 11,
                severity: 'high',
                geometry: null,
                bbox: { min_x: 126, min_y: 45, max_x: 127, max_y: 46 },
                valid_from: '2026-01-01T00:00:00Z',
                valid_to: '2026-01-02T00:00:00Z',
              },
            ],
          });
        }
        if (url.startsWith('http://api.test/api/v1/risk/pois')) {
          return jsonResponse({
            page: 1,
            page_size: 1000,
            total: 1,
            items: [
              {
                id: 101,
                name: 'poi-a',
                type: 'fire',
                lon: 126.5,
                lat: 45.5,
                alt: null,
                weight: 1,
                tags: null,
                risk_level: null,
              },
            ],
          });
        }
        if (url === 'http://api.test/api/v1/risk/evaluate') {
          expect(init?.method).toBe('POST');
          return jsonResponse({
            summary: {
              total: 1,
              duration_ms: 1,
              level_counts: { '4': 1 },
              reasons: {},
              max_level: 4,
              avg_score: 0.9,
            },
            results: [
              {
                poi_id: 101,
                level: 4,
                score: 0.9,
                factors: [],
                reasons: [
                  {
                    factor_id: 'wind',
                    factor_name: 'Wind',
                    value: 8.1,
                    threshold: 5,
                    contribution: 0.5,
                  },
                ],
              },
            ],
          });
        }
        if (url === 'http://api.test/api/v1/effects/presets') {
          return jsonResponse([]);
        }
        return jsonResponse({});
      }),
    );

    const user = userEvent.setup();
    const cesium = await import('cesium');

    render(<CesiumViewer />);
    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));
    const viewer = vi.mocked(Viewer).mock.results[0].value;

    act(() => {
      useViewModeStore.getState().enterEvent({ productId: '1' });
    });

    await waitFor(() => expect(customDataSourceMocks.instances.length).toBe(1));
    const [dataSource] = customDataSourceMocks.instances;
    await waitFor(() => expect(dataSource?.entities.add).toHaveBeenCalled());

    vi.mocked(viewer.scene.pick).mockReturnValue({ id: { id: 'risk-poi:101' } });

    act(() => {
      (
        cesium as unknown as {
          __mocks: { triggerLeftClick: (movement: { position?: unknown }) => void };
        }
      ).__mocks.triggerLeftClick({ position: { x: 12, y: 34 } });
    });

    expect(await screen.findByLabelText('Risk POI details')).toHaveTextContent('poi-a');
    expect(await screen.findByText('Wind')).toBeInTheDocument();
    expect(await screen.findByText('8.10')).toBeInTheDocument();
    expect(await screen.findByText('5.00')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '查看灾害演示' }));
    expect(await screen.findByRole('dialog', { name: '灾害演示' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '关闭' }));
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: '灾害演示' })).not.toBeInTheDocument(),
    );

    await user.click(screen.getByRole('button', { name: 'Close risk popup' }));
    await waitFor(() =>
      expect(screen.queryByLabelText('Risk POI details')).not.toBeInTheDocument(),
    );
  });

  it('handles dateline-crossing bboxes when flying camera for events', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url =
          typeof input === 'string'
            ? input
            : input instanceof URL
              ? input.toString()
              : input.url;
        if (url.endsWith('/config.json')) {
          return jsonResponse({ apiBaseUrl: 'http://api.test' });
        }
        if (url === 'http://api.test/api/v1/products/99') {
          return jsonResponse({
            id: 99,
            title: 'dateline',
            text: null,
            issued_at: '2026-01-01T00:00:00Z',
            valid_from: '2026-01-01T00:00:00Z',
            valid_to: '2026-01-02T00:00:00Z',
            version: 1,
            status: 'published',
            hazards: [
              {
                id: 1,
                severity: 'low',
                geometry: null,
                bbox: { min_x: 170, min_y: 10, max_x: 179, max_y: 20 },
                valid_from: '2026-01-01T00:00:00Z',
                valid_to: '2026-01-02T00:00:00Z',
              },
              {
                id: 2,
                severity: 'high',
                geometry: null,
                bbox: { min_x: -179, min_y: 20, max_x: 190, max_y: 10 },
                valid_from: '2026-01-01T00:00:00Z',
                valid_to: '2026-01-02T00:00:00Z',
              },
            ],
          });
        }
        if (url.startsWith('http://api.test/api/v1/risk/pois')) {
          return jsonResponse({
            page: 1,
            page_size: 1000,
            total: 0,
            items: [],
          });
        }
        if (url === 'http://api.test/api/v1/risk/evaluate') {
          return jsonResponse({
            summary: {
              total: 0,
              duration_ms: 0,
              level_counts: {},
              reasons: {},
              max_level: null,
              avg_score: null,
            },
            results: [],
          });
        }
        return jsonResponse({});
      }),
    );

    render(<CesiumViewer />);
    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;
    vi.mocked(viewer.camera.flyTo).mockClear();
    vi.mocked(Rectangle.fromDegrees).mockClear();

    act(() => {
      useViewModeStore.getState().enterEvent({ productId: '99' });
    });

    await waitFor(() => expect(Rectangle.fromDegrees).toHaveBeenCalled());

    expect(Rectangle.fromDegrees).toHaveBeenCalledWith(170, 10, -170, 20);
    expect(viewer.camera.flyTo).toHaveBeenCalledWith(
      expect.objectContaining({ duration: 1.8 }),
    );
  });

  it('aligns snow depth monitoring tiles to the most recent hour and crops to the event bbox', async () => {
    useLayerManagerStore.setState({
      layers: [
        {
          id: 'snow-depth',
          type: 'snow-depth',
          variable: 'SNOD',
          opacity: 1,
          visible: false,
          zIndex: 50,
        },
      ],
    });

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
        if (url.endsWith('/config.json')) {
          return jsonResponse({ apiBaseUrl: 'http://api.test' });
        }
        if (url === 'http://api.test/api/v1/products/1') {
          return jsonResponse({
            id: 1,
            title: '降雪',
            text: '降雪预警',
            issued_at: '2026-01-01T00:00:00Z',
            valid_from: '2026-01-01T00:45:00Z',
            valid_to: '2026-01-02T00:00:00Z',
            version: 1,
            status: 'published',
            hazards: [
              {
                id: 11,
                severity: 'high',
                geometry: null,
                bbox: { min_x: 126, min_y: 45, max_x: 127, max_y: 46 },
                valid_from: '2026-01-01T00:45:00Z',
                valid_to: '2026-01-02T00:00:00Z',
              },
            ],
          });
        }
        if (url.startsWith('http://api.test/api/v1/vectors/')) {
          return jsonResponse({
            vectors: [{ lon: 120, lat: 30, u: 1.5, v: -2 }],
          });
        }
        if (url.startsWith('http://api.test/api/v1/risk/pois')) {
          return jsonResponse({
            page: 1,
            page_size: 1000,
            total: 0,
            items: [],
          });
        }
        if (url === 'http://api.test/api/v1/risk/evaluate') {
          return jsonResponse({
            summary: {
              total: 0,
              duration_ms: 0,
              level_counts: {},
              reasons: {},
              max_level: null,
              avg_score: null,
            },
            results: [],
          });
        }
        return jsonResponse({});
      }),
    );

    render(<CesiumViewer />);
    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;
    await waitFor(() => expect(viewer.imageryLayers.add).toHaveBeenCalledTimes(1));
    viewer.imageryLayers.add.mockClear();

    act(() => {
      useViewModeStore.getState().enterEvent({ productId: '1' });
    });

    await waitFor(() => {
      const layersAdded = viewer.imageryLayers.add.mock.calls.map(([layer]: [unknown]) => layer as {
        provider?: { options?: { url?: string; rectangle?: unknown } };
      });
      const snow = layersAdded.find((layer: {
        provider?: { options?: { url?: string; rectangle?: unknown } };
      }) => {
        const url = layer.provider?.options?.url ?? '';
        return url.includes('/SNOD/') && Boolean(layer.provider?.options?.rectangle);
      });
      expect(snow?.provider?.options?.url).toContain('/20260101T000000Z/');
      expect(snow?.provider?.options?.rectangle).toEqual({
        west: 126,
        south: 45,
        east: 127,
        north: 46,
      });
    });
  });

  it('shows a monitoring notice when snow depth tiles are missing', async () => {
    useLayerManagerStore.setState({
      layers: [
        {
          id: 'snow-depth',
          type: 'snow-depth',
          variable: 'SNOD',
          opacity: 1,
          visible: true,
          zIndex: 50,
        },
      ],
    });

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
        if (url.endsWith('/config.json')) {
          return jsonResponse({ apiBaseUrl: 'http://api.test' });
        }
        if (url.includes('/api/v1/tiles/cldas/')) {
          return new Response('missing', { status: 404 });
        }
        return jsonResponse({});
      }),
    );

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    expect(await screen.findByRole('alert', { name: 'monitoring-notice' })).toHaveTextContent(
      '暂无雪深监测数据',
    );
  });

  it('requests render after clearing event entities even when the next request fails', async () => {
    render(<CesiumViewer />);
    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;
    vi.mocked(viewer.scene.requestRender).mockClear();
    vi.mocked(viewer.entities.add).mockClear();

    act(() => {
      useViewModeStore.getState().enterEvent({ productId: '1' });
    });

    await waitFor(() => expect(viewer.entities.add).toHaveBeenCalled());

    vi.mocked(viewer.entities.remove).mockClear();
    vi.mocked(viewer.scene.requestRender).mockClear();

    act(() => {
      useViewModeStore.getState().enterEvent({ productId: '2' });
    });

    await waitFor(() => expect(viewer.entities.remove).toHaveBeenCalled());
    expect(viewer.scene.requestRender).toHaveBeenCalled();

    expect(viewer.entities.add).toHaveBeenCalledTimes(1);
  });
});
