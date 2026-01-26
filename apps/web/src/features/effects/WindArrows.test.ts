import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('cesium', () => {
  const Cartesian3 = {
    fromDegrees: vi.fn((lon: number, lat: number, height: number) => ({
      kind: 'cartesian3',
      lon,
      lat,
      height,
    })),
  };

  const Ellipsoid = {
    WGS84: {
      radii: {
        x: 6378137,
      },
    },
  };

  const withAlpha = vi.fn((alpha: number) => ({ kind: 'white', alpha }));
  const Color = {
    WHITE: { kind: 'white', withAlpha },
  };

  const PolylineArrowMaterialProperty = vi.fn(function (color: unknown) {
    return { kind: 'polyline-arrow-material', color };
  });

  return { Cartesian3, Color, Ellipsoid, PolylineArrowMaterialProperty };
});

import { Cartesian3, Ellipsoid, PolylineArrowMaterialProperty } from 'cesium';
import { WindArrows, windArrowDensityForCameraHeight } from './WindArrows';

function makeViewer() {
  const entities: unknown[] = [];

  return {
    entities: {
      add: vi.fn((entity: unknown) => {
        entities.push(entity);
        return entity;
      }),
      remove: vi.fn((entity: unknown) => {
        const index = entities.indexOf(entity);
        if (index >= 0) entities.splice(index, 1);
        return true;
      }),
    },
    scene: {
      requestRender: vi.fn(),
    },
    __mocks: {
      getEntities: () => entities,
    },
  };
}

describe('WindArrows', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('adds polyline arrow entities that follow the u/v direction', () => {
    const viewer = makeViewer();
    const arrows = new WindArrows(viewer as never, {
      metersPerSecondToLength: 1000,
      minArrowLengthMeters: 1000,
      maxArrowLengthMeters: 1000,
    });

    arrows.update({
      enabled: true,
      opacity: 0.5,
      lowModeEnabled: false,
      vectors: [
        { lon: 0, lat: 0, u: 5, v: 0 }, // east
        { lon: 0, lat: 0, u: 0, v: 5 }, // north
      ],
    });

    expect(viewer.entities.add).toHaveBeenCalledTimes(2);
    expect(vi.mocked(PolylineArrowMaterialProperty)).toHaveBeenCalledTimes(1);

    const calls = vi.mocked(Cartesian3.fromDegrees).mock.calls;
    expect(calls).toHaveLength(4);

    expect(calls[0]).toEqual([0, 0, 0]);
    expect(calls[1]?.[0]).toBeGreaterThan(0);
    expect(calls[1]?.[1]).toBeCloseTo(0, 6);

    expect(calls[2]).toEqual([0, 0, 0]);
    expect(calls[3]?.[0]).toBeCloseTo(0, 6);
    expect(calls[3]?.[1]).toBeGreaterThan(0);

    expect(viewer.scene.requestRender).toHaveBeenCalled();
  });

  it('clamps arrows to the ground when no shell is active', () => {
    const viewer = makeViewer();
    const arrows = new WindArrows(viewer as never, {
      metersPerSecondToLength: 1000,
      minArrowLengthMeters: 1000,
      maxArrowLengthMeters: 1000,
    });

    arrows.update({
      enabled: true,
      opacity: 1,
      lowModeEnabled: false,
      vectors: [{ lon: 0, lat: 0, u: 5, v: 0 }],
    });

    const calls = vi.mocked(Cartesian3.fromDegrees).mock.calls;
    expect(calls[0]).toEqual([0, 0, 0]);

    const entities = (viewer as unknown as { __mocks: { getEntities: () => any[] } }).__mocks.getEntities();
    expect(entities[0]?.polyline?.clampToGround).toBe(true);
  });

  it('renders arrows at the shell height when a layerGlobal shell is active', () => {
    const viewer = makeViewer();
    (viewer as unknown as { terrainProvider?: unknown }).terrainProvider = {
      tilingScheme: {
        ellipsoid: {
          radii: {
            x: Ellipsoid.WGS84.radii.x + 8000,
          },
        },
      },
    };

    const arrows = new WindArrows(viewer as never, {
      metersPerSecondToLength: 1000,
      minArrowLengthMeters: 1000,
      maxArrowLengthMeters: 1000,
    });

    arrows.update({
      enabled: true,
      opacity: 1,
      lowModeEnabled: false,
      vectors: [{ lon: 0, lat: 0, u: 5, v: 0 }],
    });

    const calls = vi.mocked(Cartesian3.fromDegrees).mock.calls;
    expect(calls[0]?.[2]).toBeGreaterThan(0);

    const entities = (viewer as unknown as { __mocks: { getEntities: () => any[] } }).__mocks.getEntities();
    expect(entities[0]?.polyline?.clampToGround).toBe(false);
  });

  it('skips rendering when update inputs are invalid', () => {
    const viewer = makeViewer();
    const arrows = new WindArrows(viewer as never, {
      metersPerSecondToLength: 1000,
      minArrowLengthMeters: 1000,
      maxArrowLengthMeters: 1000,
    });

    arrows.update({
      enabled: true,
      opacity: Number.NaN,
      lowModeEnabled: false,
      vectors: [{ lon: 0, lat: 0, u: 5, v: 0 }],
    });

    arrows.update({
      enabled: true,
      opacity: -1,
      lowModeEnabled: false,
      vectors: [{ lon: 0, lat: 0, u: 5, v: 0 }],
    });

    arrows.update({
      enabled: true,
      opacity: 1,
      lowModeEnabled: false,
      vectors: null as never,
    });

    expect(viewer.entities.add).not.toHaveBeenCalled();
  });

  it('handles invalid vectors and terrainProvider access errors without crashing', () => {
    const viewer = makeViewer();
    Object.defineProperty(viewer, 'terrainProvider', {
      get() {
        throw new Error('terrainProvider unavailable');
      },
    });

    const arrows = new WindArrows(viewer as never, {
      metersPerSecondToLength: 1000,
      minArrowLengthMeters: 1000,
      maxArrowLengthMeters: 1000,
    });

    arrows.update({
      enabled: true,
      opacity: 1,
      lowModeEnabled: false,
      vectors: [
        { lon: 0, lat: 0, u: 0, v: 0 }, // speed=0, skipped
        { lon: Number.NaN, lat: Number.NaN, u: 5, v: 0 }, // wraps/clamps + renders
        { lon: 0, lat: 0, u: Number.NaN, v: 5 }, // non-finite speed, skipped
      ],
    });

    expect(viewer.entities.add).toHaveBeenCalledTimes(1);
    expect(vi.mocked(Cartesian3.fromDegrees)).toHaveBeenCalled();
  });

  it('clears entities when disabled', () => {
    const viewer = makeViewer();
    const arrows = new WindArrows(viewer as never, {
      metersPerSecondToLength: 1000,
      minArrowLengthMeters: 1000,
      maxArrowLengthMeters: 1000,
    });

    arrows.update({
      enabled: true,
      opacity: 1,
      lowModeEnabled: false,
      vectors: [{ lon: 0, lat: 0, u: 1, v: 0 }],
    });

    expect(viewer.entities.add).toHaveBeenCalledTimes(1);
    expect((viewer as unknown as { __mocks: { getEntities: () => unknown[] } }).__mocks.getEntities())
      .toHaveLength(1);

    arrows.update({
      enabled: false,
      opacity: 1,
      lowModeEnabled: false,
      vectors: [{ lon: 0, lat: 0, u: 1, v: 0 }],
    });

    expect(viewer.entities.remove).toHaveBeenCalledTimes(1);
    expect((viewer as unknown as { __mocks: { getEntities: () => unknown[] } }).__mocks.getEntities())
      .toHaveLength(0);
  });

  it('honors maxArrows and reduces arrow count in performance mode (default)', () => {
    const viewer = makeViewer();
    const arrows = new WindArrows(viewer as never, { maxArrows: 2 });

    arrows.update({
      enabled: true,
      opacity: 1,
      lowModeEnabled: false,
      vectors: [
        { lon: 0, lat: 0, u: 1, v: 0 },
        { lon: 1, lat: 1, u: 1, v: 0 },
        { lon: 2, lat: 2, u: 1, v: 0 },
        { lon: 3, lat: 3, u: 1, v: 0 },
      ],
    });

    expect(viewer.entities.add).toHaveBeenCalledTimes(2);

    arrows.update({
      enabled: true,
      opacity: 1,
      lowModeEnabled: true,
      vectors: [
        { lon: 0, lat: 0, u: 1, v: 0 },
        { lon: 1, lat: 1, u: 1, v: 0 },
        { lon: 2, lat: 2, u: 1, v: 0 },
        { lon: 3, lat: 3, u: 1, v: 0 },
      ],
    });

    expect(viewer.entities.remove).toHaveBeenCalledTimes(2);
    expect(viewer.entities.add).toHaveBeenCalledTimes(3);
    expect((viewer as unknown as { __mocks: { getEntities: () => unknown[] } }).__mocks.getEntities())
      .toHaveLength(1);
  });
});

describe('windArrowDensityForCameraHeight', () => {
  it('returns higher density for lower camera heights', () => {
    expect(
      windArrowDensityForCameraHeight({
        cameraHeightMeters: 50_000,
        lowModeEnabled: false,
      }),
    ).toBe(32);

    expect(
      windArrowDensityForCameraHeight({
        cameraHeightMeters: 600_000,
        lowModeEnabled: false,
      }),
    ).toBe(20);

    expect(
      windArrowDensityForCameraHeight({
        cameraHeightMeters: 30_000_000,
        lowModeEnabled: false,
      }),
    ).toBe(4);

    expect(
      windArrowDensityForCameraHeight({
        cameraHeightMeters: 15_000_000,
        lowModeEnabled: false,
      }),
    ).toBe(6);

    expect(
      windArrowDensityForCameraHeight({
        cameraHeightMeters: 7_000_000,
        lowModeEnabled: false,
      }),
    ).toBe(8);

    expect(
      windArrowDensityForCameraHeight({
        cameraHeightMeters: 3_000_000,
        lowModeEnabled: false,
      }),
    ).toBe(12);

    expect(
      windArrowDensityForCameraHeight({
        cameraHeightMeters: 1_500_000,
        lowModeEnabled: false,
      }),
    ).toBe(16);

    expect(
      windArrowDensityForCameraHeight({
        cameraHeightMeters: 250_000,
        lowModeEnabled: false,
      }),
    ).toBe(24);

    expect(
      windArrowDensityForCameraHeight({
        cameraHeightMeters: 150_000,
        lowModeEnabled: false,
      }),
    ).toBe(28);
  });

  it('reduces density in performance mode and handles missing heights', () => {
    expect(
      windArrowDensityForCameraHeight({
        cameraHeightMeters: 600_000,
        lowModeEnabled: true,
      }),
    ).toBe(10);

    expect(
      windArrowDensityForCameraHeight({
        cameraHeightMeters: null,
        lowModeEnabled: false,
      }),
    ).toBe(12);

    expect(
      windArrowDensityForCameraHeight({
        cameraHeightMeters: null,
        lowModeEnabled: true,
      }),
    ).toBe(6);
  });
});
