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

  const viewer = {
    camera,
    homeButton: {
      viewModel: {
        command: {
          beforeExecute
        }
      }
    },
    scene: {
      requestRenderMode: false,
      maximumRenderTimeChange: 0,
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
    OpenStreetMapImageryProvider: vi.fn(),
    Math: {
      toDegrees: vi.fn((radians: number) => radians)
    }
  };
});

import { Viewer } from 'cesium';
import { CesiumViewer } from './CesiumViewer';

describe('CesiumViewer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
});
