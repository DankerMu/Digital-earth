import {
  Cartesian3,
  Math as CesiumMath,
  SceneMode,
  type Rectangle,
  type Viewer,
} from 'cesium';

import { requestViewerRender } from '../../lib/cesiumSafe';
import type { SceneModeId } from '../../state/sceneMode';

type CapturedCameraView = {
  destination: Cartesian3 | Rectangle;
  heading: number;
  pitch: number;
  roll: number;
};

export function sceneModeIdToCesium(modeId: SceneModeId): SceneMode {
  if (modeId === '2d') return SceneMode.SCENE2D;
  if (modeId === 'columbus') return SceneMode.COLUMBUS_VIEW;
  return SceneMode.SCENE3D;
}

export function cesiumSceneModeToId(mode: SceneMode): SceneModeId | null {
  if (mode === SceneMode.SCENE2D) return '2d';
  if (mode === SceneMode.COLUMBUS_VIEW) return 'columbus';
  if (mode === SceneMode.SCENE3D) return '3d';
  return null;
}

function captureCameraView(viewer: Viewer): CapturedCameraView {
  const camera = viewer.camera;

  const rectangle =
    typeof camera.computeViewRectangle === 'function' ? camera.computeViewRectangle() : null;

  const heading = camera.heading;
  const pitch = camera.pitch;
  const roll = camera.roll ?? 0;

  if (rectangle) return { destination: rectangle, heading, pitch, roll };

  const cartographic = camera.positionCartographic;
  if (
    Number.isFinite(cartographic.longitude) &&
    Number.isFinite(cartographic.latitude) &&
    Number.isFinite(cartographic.height)
  ) {
    return {
      destination: Cartesian3.fromRadians(
        cartographic.longitude,
        cartographic.latitude,
        Math.max(0, cartographic.height),
      ),
      heading,
      pitch,
      roll,
    };
  }

  return {
    destination: Cartesian3.clone(camera.position),
    heading,
    pitch,
    roll,
  };
}

function restoreCameraView(viewer: Viewer, view: CapturedCameraView, modeId: SceneModeId) {
  const camera = viewer.camera;

  if (modeId === '2d') {
    camera.setView({
      destination: view.destination,
      orientation: { heading: view.heading, pitch: -CesiumMath.PI_OVER_TWO, roll: 0 },
    });
    return;
  }

  camera.setView({
    destination: view.destination,
    orientation: { heading: view.heading, pitch: view.pitch, roll: view.roll },
  });
}

export type SwitchSceneModeOptions = {
  duration?: number;
};

export function switchViewerSceneMode(
  viewer: Viewer,
  modeId: SceneModeId,
  options: SwitchSceneModeOptions = {},
): () => void {
  const target = sceneModeIdToCesium(modeId);

  if (viewer.scene.mode === target) return () => {};

  const duration = options.duration ?? 0.8;
  const captured = captureCameraView(viewer);

  const handler = () => {
    viewer.scene.morphComplete.removeEventListener(handler);
    restoreCameraView(viewer, captured, modeId);
    requestViewerRender(viewer);
  };

  viewer.scene.morphComplete.addEventListener(handler);

  if (modeId === '2d') {
    viewer.scene.morphTo2D(duration);
  } else if (modeId === 'columbus') {
    viewer.scene.morphToColumbusView(duration);
  } else {
    viewer.scene.morphTo3D(duration);
  }

  return () => {
    viewer.scene.morphComplete.removeEventListener(handler);
  };
}
