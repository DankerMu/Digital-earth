import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('cesium', () => {
  const SceneMode = {
    MORPHING: 0,
    COLUMBUS_VIEW: 1,
    SCENE2D: 2,
    SCENE3D: 3
  };

  const createWorldTerrainAsync = vi.fn(async () => ({ terrain: true }));
  const EllipsoidTerrainProvider = vi.fn(function () {
    return { ellipsoidTerrain: true };
  });
  const Ion = { defaultAccessToken: '' };
  const GeographicTilingScheme = vi.fn(() => ({ kind: 'geographic' }));

  let morphCompleteHandler: (() => void) | null = null;

  const camera = {
    heading: 1,
    pitch: 0.5,
    roll: 0.1,
    position: { x: 1, y: 2, z: 3 },
    positionCartographic: { longitude: 0.1, latitude: 0.2, height: 123 },
    computeViewRectangle: vi.fn(() => null),
    setView: vi.fn(),
    flyTo: vi.fn()
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

  const viewer = {
    camera,
    homeButton: {
      viewModel: {
        command: {
          beforeExecute
        }
      }
    },
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
      screenSpaceCameraController: {
        minimumZoomDistance: 0,
        maximumZoomDistance: 0
      },
      postRender: {
        addEventListener: vi.fn(),
        removeEventListener: vi.fn()
      }
    },
    destroy: vi.fn()
  };

  return {
    SceneMode,
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
import { DEFAULT_EVENT_LAYER_MODE, useEventLayersStore } from '../../state/eventLayers';
import { useLayerManagerStore } from '../../state/layerManager';
import { DEFAULT_SCENE_MODE_ID, useSceneModeStore } from '../../state/sceneMode';
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
    clearConfigCache();
    localStorage.removeItem('digital-earth.basemap');
    localStorage.removeItem('digital-earth.eventLayers');
    localStorage.removeItem('digital-earth.sceneMode');
    localStorage.removeItem('digital-earth.layers');
    useBasemapStore.setState({ basemapId: DEFAULT_BASEMAP_ID });
    useEventLayersStore.setState({ enabled: false, mode: DEFAULT_EVENT_LAYER_MODE });
    useSceneModeStore.setState({ sceneModeId: DEFAULT_SCENE_MODE_ID });
    useLayerManagerStore.setState({ layers: [] });
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ apiBaseUrl: 'http://api.test' })));
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

  it('refreshes cloud tiles over time', async () => {
    const CLOUD_LAYER_REFRESH_INTERVAL_MS = 5 * 60 * 1000;
    let triggerRefresh: (() => void) | null = null;
    const setIntervalSpy = vi
      .spyOn(window, 'setInterval')
      .mockImplementation((handler: TimerHandler, timeout?: number, ...args: unknown[]) => {
        void args;
        if (timeout === CLOUD_LAYER_REFRESH_INTERVAL_MS && typeof handler === 'function') {
          triggerRefresh = handler;
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
});
