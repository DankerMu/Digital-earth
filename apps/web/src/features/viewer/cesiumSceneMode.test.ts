import { describe, expect, it, vi } from 'vitest';

vi.mock('cesium', () => {
  const SceneMode = {
    MORPHING: 0,
    COLUMBUS_VIEW: 1,
    SCENE2D: 2,
    SCENE3D: 3,
  };

  return {
    SceneMode,
    Math: { PI_OVER_TWO: Math.PI / 2 },
    Cartesian3: {
      fromRadians: vi.fn(() => ({ destinationRadians: true })),
      clone: vi.fn(() => ({ destinationCloned: true })),
    },
  };
});

import { SceneMode } from 'cesium';
import { cesiumSceneModeToId, sceneModeIdToCesium, switchViewerSceneMode } from './cesiumSceneMode';

describe('cesiumSceneMode', () => {
  it('maps app ids to Cesium SceneMode values', () => {
    expect(sceneModeIdToCesium('3d')).toBe(SceneMode.SCENE3D);
    expect(sceneModeIdToCesium('2d')).toBe(SceneMode.SCENE2D);
    expect(sceneModeIdToCesium('columbus')).toBe(SceneMode.COLUMBUS_VIEW);
  });

  it('maps Cesium SceneMode values to app ids', () => {
    expect(cesiumSceneModeToId(SceneMode.SCENE3D)).toBe('3d');
    expect(cesiumSceneModeToId(SceneMode.SCENE2D)).toBe('2d');
    expect(cesiumSceneModeToId(SceneMode.COLUMBUS_VIEW)).toBe('columbus');
    expect(cesiumSceneModeToId(SceneMode.MORPHING)).toBeNull();
  });

  it('switches to Columbus view and restores camera', () => {
    let morphCompleteHandler: (() => void) | null = null;

    const camera = {
      heading: 0.2,
      pitch: 0.3,
      roll: 0.4,
      position: { x: 1, y: 2, z: 3 },
      positionCartographic: { longitude: 0, latitude: 0, height: 100 },
      computeViewRectangle: vi.fn(() => ({ rect: true })),
      setView: vi.fn(),
    };

    const scene = {
      mode: SceneMode.SCENE3D,
      requestRender: vi.fn(),
      morphComplete: {
        addEventListener: vi.fn((handler: () => void) => {
          morphCompleteHandler = handler;
        }),
        removeEventListener: vi.fn(),
      },
      morphTo2D: vi.fn(() => {
        scene.mode = SceneMode.SCENE2D;
      }),
      morphTo3D: vi.fn(() => {
        scene.mode = SceneMode.SCENE3D;
      }),
      morphToColumbusView: vi.fn(() => {
        scene.mode = SceneMode.COLUMBUS_VIEW;
      }),
    };

    const viewer = { camera, scene } as unknown as import('cesium').Viewer;

    switchViewerSceneMode(viewer, 'columbus', { duration: 0.25 });

    expect(scene.morphToColumbusView).toHaveBeenCalledWith(0.25);
    expect(morphCompleteHandler).toBeTypeOf('function');

    // TypeScript can't track the mock side-effect, so use assertion
    (morphCompleteHandler as () => void)();

    expect(camera.setView).toHaveBeenCalledWith({
      destination: { rect: true },
      orientation: {
        heading: 0.2,
        pitch: 0.3,
        roll: 0.4,
      },
    });
    expect(scene.requestRender).toHaveBeenCalled();
  });
});

