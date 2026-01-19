import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('cesium', () => {
  const camera = {
    heading: 1,
    pitch: 0.5,
    position: { x: 1, y: 2, z: 3 },
    setView: vi.fn(),
    flyTo: vi.fn()
  };

  const beforeExecute = {
    addEventListener: vi.fn(),
    removeEventListener: vi.fn()
  };

  const baseLayer = { baseLayer: true };

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
      addImageryProvider: vi.fn(() => baseLayer)
    },
    scene: {
      requestRenderMode: false,
      maximumRenderTimeChange: 0,
      requestRender: vi.fn(),
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
    Viewer: vi.fn(function () {
      return viewer;
    }),
    ImageryLayer: vi.fn(function () {
      return { baseLayer: true };
    }),
    Cartesian3: {
      fromDegrees: vi.fn(() => ({ destination: true })),
      clone: vi.fn((value: unknown) => ({ ...(value as Record<string, unknown>), cloned: true }))
    },
    WebMapTileServiceImageryProvider: vi.fn(),
    UrlTemplateImageryProvider: vi.fn(),
    WebMercatorTilingScheme: vi.fn(),
    Math: {
      toDegrees: vi.fn((radians: number) => radians)
    }
  };
});

import { Viewer } from 'cesium';
import { DEFAULT_BASEMAP_ID } from '../../config/basemaps';
import { useBasemapStore } from '../../state/basemap';
import { CesiumViewer } from './CesiumViewer';

describe('CesiumViewer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.removeItem('digital-earth.basemap');
    useBasemapStore.setState({ basemapId: DEFAULT_BASEMAP_ID });
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
});
