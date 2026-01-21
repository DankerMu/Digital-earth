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
  const EllipsoidTerrainProvider = vi.fn(function () {
    return { ellipsoidTerrain: true };
  });
  const Ion = { defaultAccessToken: '' };
  const GeographicTilingScheme = vi.fn(() => ({ kind: 'geographic' }));

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
        ellipsoid: { kind: 'ellipsoid' },
      },
      fog: {
        enabled: false,
        density: 0,
        screenSpaceErrorFactor: 0,
        minimumBrightness: 0,
      },
      skyBox: { show: false },
      skyAtmosphere: { show: false },
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
    EllipsoidTerrainProvider,
    Ion,
  };
});

import { EllipsoidTerrainProvider, createWorldTerrainAsync, Viewer } from 'cesium';
import { clearConfigCache } from '../../config';
import { DEFAULT_BASEMAP_ID } from '../../config/basemaps';
import { useBasemapStore } from '../../state/basemap';
import { DEFAULT_CAMERA_PERSPECTIVE_ID, useCameraPerspectiveStore } from '../../state/cameraPerspective';
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
    clearConfigCache();
    localStorage.removeItem('digital-earth.basemap');
    localStorage.removeItem('digital-earth.eventLayers');
    localStorage.removeItem('digital-earth.sceneMode');
    localStorage.removeItem('digital-earth.layers');
    localStorage.removeItem('digital-earth.performanceMode');
    localStorage.removeItem('digital-earth.viewMode');
    localStorage.removeItem('digital-earth.cameraPerspective');
    useBasemapStore.setState({ basemapId: DEFAULT_BASEMAP_ID });
    useCameraPerspectiveStore.setState({ cameraPerspectiveId: DEFAULT_CAMERA_PERSPECTIVE_ID });
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
        if (url.startsWith('http://api.test/api/v1/vectors/')) {
          return jsonResponse({
            vectors: [{ lon: 120, lat: 30, u: 1.5, v: -2 }],
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
      ],
    });

    render(<CesiumViewer />);

    await waitFor(() => expect(vi.mocked(Viewer)).toHaveBeenCalledTimes(1));

    const viewer = vi.mocked(Viewer).mock.results[0].value;

    await waitFor(() => expect(viewer.imageryLayers.raiseToTop).toHaveBeenCalledTimes(3));

    const raisedUrls = viewer.imageryLayers.raiseToTop.mock.calls.map(
      ([layer]: [unknown]) =>
        (layer as { provider?: { options?: { url?: string } } })?.provider?.options?.url ?? '',
    );

    expect(raisedUrls[0]).toContain('/LOW/');
    expect(raisedUrls[1]).toContain('/TCC/');
    expect(raisedUrls[2]).toContain('/precipitation/');
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
});
