import { Cartesian3, Math as CesiumMath, Transforms, type Camera } from 'cesium';

export type LocalModeBBox = {
  west: number;
  south: number;
  east: number;
  north: number;
  bottom: number;
  top: number;
};

const METERS_PER_DEG_LAT = 111_320;

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

function readFrustumParams(frustum: unknown): { fovYRad: number; aspectRatio: number } {
  const fallbackFovYRad = CesiumMath.toRadians(60);
  const fallbackAspectRatio = 1;
  if (!frustum || typeof frustum !== 'object') {
    return { fovYRad: fallbackFovYRad, aspectRatio: fallbackAspectRatio };
  }

  const fovRaw = (frustum as { fov?: unknown; fovy?: unknown }).fov;
  const fovyRaw = (frustum as { fov?: unknown; fovy?: unknown }).fovy;
  const aspectRaw = (frustum as { aspectRatio?: unknown }).aspectRatio;

  const fovYRadCandidate =
    typeof fovRaw === 'number'
      ? fovRaw
      : typeof fovyRaw === 'number'
        ? fovyRaw
        : fallbackFovYRad;
  const fovYRad = Number.isFinite(fovYRadCandidate) ? clamp(fovYRadCandidate, 0.1, Math.PI - 0.1) : fallbackFovYRad;

  const aspectCandidate = typeof aspectRaw === 'number' ? aspectRaw : fallbackAspectRatio;
  const aspectRatio = Number.isFinite(aspectCandidate) ? clamp(aspectCandidate, 0.2, 10) : fallbackAspectRatio;

  return { fovYRad, aspectRatio };
}

function estimateRangeMeters(camera: Camera, options: { topMeters: number }): number {
  const cameraHeightMeters = camera.positionCartographic?.height ?? 0;
  const targetTopMeters = options.topMeters;

  const directionWC = (camera as unknown as { directionWC?: Cartesian3 }).directionWC;
  const positionWC = (camera as unknown as { positionWC?: Cartesian3 }).positionWC;

  if (!directionWC || !positionWC) {
    return clamp(cameraHeightMeters * 2, 5_000, 50_000);
  }

  const frame = Transforms.eastNorthUpToFixedFrame(positionWC);
  const upWorld = new Cartesian3(frame[8], frame[9], frame[10]);
  const dirUp = Cartesian3.dot(directionWC, upWorld);

  const deltaH = targetTopMeters - cameraHeightMeters;
  if (!Number.isFinite(dirUp) || dirUp <= 0.05 || !Number.isFinite(deltaH)) {
    return clamp(cameraHeightMeters * 2, 5_000, 50_000);
  }

  const t = deltaH / dirUp;
  if (!Number.isFinite(t) || t <= 0) {
    return clamp(cameraHeightMeters * 2, 5_000, 50_000);
  }

  return clamp(t, 5_000, 50_000);
}

export function computeLocalModeBBox(camera: Camera): LocalModeBBox {
  const position = camera.positionCartographic;
  const lonDeg = CesiumMath.toDegrees(position.longitude);
  const latDeg = CesiumMath.toDegrees(position.latitude);

  const bottom = 0;
  const top = 12_000;

  const { fovYRad, aspectRatio } = readFrustumParams((camera as unknown as { frustum?: unknown }).frustum);

  const rangeMeters = estimateRangeMeters(camera, { topMeters: top });
  const halfFovY = fovYRad * 0.5;
  const halfFovX = Math.atan(Math.tan(halfFovY) * aspectRatio);
  const halfY = Math.tan(halfFovY) * rangeMeters;
  const halfX = Math.tan(halfFovX) * rangeMeters;
  const radiusMeters = clamp(Math.max(halfX, halfY, 5_000), 1_000, 50_000);

  const latRad = CesiumMath.toRadians(latDeg);
  const metersPerDegLon = Math.max(1e-6, METERS_PER_DEG_LAT * Math.cos(latRad));

  const deltaLat = radiusMeters / METERS_PER_DEG_LAT;
  const deltaLon = radiusMeters / metersPerDegLon;

  const clampedLat = clamp(latDeg, -90, 90);
  const clampedLon = clamp(lonDeg, -180, 180);

  return {
    west: clamp(clampedLon - deltaLon, -180, 180),
    south: clamp(clampedLat - deltaLat, -90, 90),
    east: clamp(clampedLon + deltaLon, -180, 180),
    north: clamp(clampedLat + deltaLat, -90, 90),
    bottom,
    top,
  };
}
