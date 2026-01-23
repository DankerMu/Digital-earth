import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('cesium', () => {
  class Cartesian3 {
    x: number;
    y: number;
    z: number;
    constructor(x = 0, y = 0, z = 0) {
      this.x = x;
      this.y = y;
      this.z = z;
    }

    static dot(a: Cartesian3, b: Cartesian3) {
      return a.x * b.x + a.y * b.y + a.z * b.z;
    }
  }

  const CesiumMath = {
    toRadians: (deg: number) => (deg * Math.PI) / 180,
    toDegrees: (rad: number) => (rad * 180) / Math.PI,
  };

  const Transforms = {
    eastNorthUpToFixedFrame: vi.fn(() => [
      1, 0, 0, 0,
      0, 1, 0, 0,
      0, 0, 1, 0,
      0, 0, 0, 1,
    ]),
  };

  return {
    Cartesian3,
    Math: CesiumMath,
    Transforms,
  };
});

import { Math as CesiumMath, Transforms } from 'cesium';
import { computeLocalModeBBox } from './bboxCalculator';

describe('computeLocalModeBBox', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const baseCamera = {
    positionCartographic: {
      longitude: CesiumMath.toRadians(10),
      latitude: CesiumMath.toRadians(20),
      height: 3000,
    },
    frustum: { fov: CesiumMath.toRadians(60), aspectRatio: 1 },
    positionWC: { x: 0, y: 0, z: 0 },
    directionWC: { x: 0, y: 0, z: 1 },
  } as const;

  const makeCamera = (overrides: Record<string, unknown> = {}) =>
    ({
      ...baseCamera,
      ...overrides,
      positionCartographic: {
        ...baseCamera.positionCartographic,
        ...((overrides.positionCartographic as Record<string, unknown> | undefined) ?? {}),
      },
    }) as never;

  const spanDeg = (bbox: { west: number; south: number; east: number; north: number }) => ({
    lon: bbox.east - bbox.west,
    lat: bbox.north - bbox.south,
  });

  it('returns a bounded 3D bbox around the camera', () => {
    const bbox = computeLocalModeBBox(makeCamera());
    expect(bbox.bottom).toBe(0);
    expect(bbox.top).toBe(12000);
    expect(bbox.west).toBeLessThan(bbox.east);
    expect(bbox.south).toBeLessThan(bbox.north);
    expect((bbox.west + bbox.east) / 2).toBeCloseTo(10, 1);
    expect((bbox.south + bbox.north) / 2).toBeCloseTo(20, 1);
  });

  it('clamps non-finite inputs to min (via longitude)', () => {
    const bbox = computeLocalModeBBox(
      makeCamera({
        positionCartographic: {
          longitude: Number.NaN,
        },
      }),
    );

    expect(bbox.west).toBe(-180);
    expect(bbox.east).toBeGreaterThan(-180);
    expect(Number.isFinite(bbox.south)).toBe(true);
    expect(Number.isFinite(bbox.north)).toBe(true);
  });

  it('clamps values below min (via longitude)', () => {
    const bbox = computeLocalModeBBox(
      makeCamera({
        positionCartographic: {
          longitude: CesiumMath.toRadians(-200),
        },
      }),
    );

    expect(bbox.west).toBe(-180);
    expect(bbox.east).toBeGreaterThan(-180);
  });

  it('clamps values above max (via longitude)', () => {
    const bbox = computeLocalModeBBox(
      makeCamera({
        positionCartographic: {
          longitude: CesiumMath.toRadians(200),
        },
      }),
    );

    expect(bbox.east).toBe(180);
    expect(bbox.west).toBeLessThan(180);
  });

  it.each([
    ['null', null],
    ['non-object', 123],
  ])('uses frustum fallbacks when frustum is %s', (_label, frustum) => {
    const baseline = computeLocalModeBBox(makeCamera({ positionCartographic: { height: 0 } }));
    const fallback = computeLocalModeBBox(makeCamera({ positionCartographic: { height: 0 }, frustum }));

    expect(spanDeg(fallback).lon).toBeCloseTo(spanDeg(baseline).lon, 10);
    expect(spanDeg(fallback).lat).toBeCloseTo(spanDeg(baseline).lat, 10);
  });

  it('prefers frustum.fovy when frustum.fov is missing', () => {
    const baseline = computeLocalModeBBox(makeCamera({ positionCartographic: { height: 0 } }));
    const fovy = computeLocalModeBBox(
      makeCamera({
        positionCartographic: { height: 0 },
        frustum: { fovy: CesiumMath.toRadians(45), aspectRatio: 1 },
      }),
    );

    expect(spanDeg(fovy).lon).toBeLessThan(spanDeg(baseline).lon);
    expect(spanDeg(fovy).lat).toBeLessThan(spanDeg(baseline).lat);
  });

  it('falls back when frustum params are invalid (non-finite fov/aspect)', () => {
    const baseline = computeLocalModeBBox(makeCamera({ positionCartographic: { height: 0 } }));

    const badFov = computeLocalModeBBox(
      makeCamera({
        positionCartographic: { height: 0 },
        frustum: { fov: Number.POSITIVE_INFINITY, aspectRatio: 1 },
      }),
    );
    expect(spanDeg(badFov).lon).toBeCloseTo(spanDeg(baseline).lon, 10);

    const badAspect = computeLocalModeBBox(
      makeCamera({
        positionCartographic: { height: 0 },
        frustum: { fov: CesiumMath.toRadians(60), aspectRatio: Number.POSITIVE_INFINITY },
      }),
    );
    expect(spanDeg(badAspect).lat).toBeCloseTo(spanDeg(baseline).lat, 10);
  });

  it('falls back when frustum values are wrong types (fov/fovy/aspect)', () => {
    const baseline = computeLocalModeBBox(makeCamera({ positionCartographic: { height: 0 } }));
    const fallback = computeLocalModeBBox(
      makeCamera({
        positionCartographic: { height: 0 },
        frustum: { fov: 'nope', fovy: false, aspectRatio: 'nope' },
      }),
    );

    expect(spanDeg(fallback).lon).toBeCloseTo(spanDeg(baseline).lon, 10);
    expect(spanDeg(fallback).lat).toBeCloseTo(spanDeg(baseline).lat, 10);
  });

  it('falls back when directionWC is missing', () => {
    const camera = makeCamera({ directionWC: undefined });
    computeLocalModeBBox(camera);
    expect(Transforms.eastNorthUpToFixedFrame).not.toHaveBeenCalled();
  });

  it('treats missing camera height as 0', () => {
    const cameraWithoutHeight = makeCamera({ positionCartographic: { height: undefined }, directionWC: undefined });
    const cameraWithZeroHeight = makeCamera({ positionCartographic: { height: 0 }, directionWC: undefined });

    const bboxWithoutHeight = computeLocalModeBBox(cameraWithoutHeight);
    const bboxWithZeroHeight = computeLocalModeBBox(cameraWithZeroHeight);

    expect(spanDeg(bboxWithoutHeight).lon).toBeCloseTo(spanDeg(bboxWithZeroHeight).lon, 10);
    expect(spanDeg(bboxWithoutHeight).lat).toBeCloseTo(spanDeg(bboxWithZeroHeight).lat, 10);
  });

  it('falls back when positionWC is missing', () => {
    const camera = makeCamera({ positionWC: undefined });
    computeLocalModeBBox(camera);
    expect(Transforms.eastNorthUpToFixedFrame).not.toHaveBeenCalled();
  });

  it('falls back when dirUp is near zero', () => {
    const baseline = computeLocalModeBBox(makeCamera());
    vi.clearAllMocks();
    const camera = makeCamera({ directionWC: { x: 1, y: 0, z: 0.01 } });
    const bbox = computeLocalModeBBox(camera);

    expect(Transforms.eastNorthUpToFixedFrame).toHaveBeenCalledTimes(1);
    expect(spanDeg(bbox).lon).toBeLessThan(spanDeg(baseline).lon);
  });

  it('falls back when dirUp is non-finite', () => {
    const camera = makeCamera({ directionWC: { x: 0, y: 0, z: Number.NaN } });
    const bbox = computeLocalModeBBox(camera);

    expect(Transforms.eastNorthUpToFixedFrame).toHaveBeenCalledTimes(1);
    expect(Number.isFinite(bbox.west)).toBe(true);
    expect(Number.isFinite(bbox.east)).toBe(true);
  });

  it('falls back when deltaH is non-finite', () => {
    const camera = makeCamera({ positionCartographic: { height: Number.NaN } });
    const bbox = computeLocalModeBBox(camera);

    expect(Transforms.eastNorthUpToFixedFrame).toHaveBeenCalledTimes(1);
    expect(Number.isFinite(bbox.west)).toBe(true);
    expect(Number.isFinite(bbox.east)).toBe(true);
  });

  it('falls back when t is behind the camera (t <= 0)', () => {
    const baseline = computeLocalModeBBox(makeCamera());
    vi.clearAllMocks();
    const camera = makeCamera({ positionCartographic: { height: 13_000 } });
    const bbox = computeLocalModeBBox(camera);

    expect(Transforms.eastNorthUpToFixedFrame).toHaveBeenCalledTimes(1);
    expect(spanDeg(bbox).lon).toBeGreaterThan(spanDeg(baseline).lon);
  });
});
