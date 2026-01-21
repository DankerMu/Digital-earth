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

  const withAlpha = vi.fn((alpha: number) => ({ kind: 'white', alpha }));
  const Color = {
    WHITE: { kind: 'white', withAlpha },
  };

  const PolylineArrowMaterialProperty = vi.fn(function (color: unknown) {
    return { kind: 'polyline-arrow-material', color };
  });

  return { Cartesian3, Color, PolylineArrowMaterialProperty };
});

import { Cartesian3, PolylineArrowMaterialProperty } from 'cesium';
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
      performanceModeEnabled: false,
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
      performanceModeEnabled: false,
      vectors: [{ lon: 0, lat: 0, u: 1, v: 0 }],
    });

    expect(viewer.entities.add).toHaveBeenCalledTimes(1);
    expect((viewer as unknown as { __mocks: { getEntities: () => unknown[] } }).__mocks.getEntities())
      .toHaveLength(1);

    arrows.update({
      enabled: false,
      opacity: 1,
      performanceModeEnabled: false,
      vectors: [{ lon: 0, lat: 0, u: 1, v: 0 }],
    });

    expect(viewer.entities.remove).toHaveBeenCalledTimes(1);
    expect((viewer as unknown as { __mocks: { getEntities: () => unknown[] } }).__mocks.getEntities())
      .toHaveLength(0);
  });

  it('honors maxArrows and disables itself in performance mode (default)', () => {
    const viewer = makeViewer();
    const arrows = new WindArrows(viewer as never, { maxArrows: 2 });

    arrows.update({
      enabled: true,
      opacity: 1,
      performanceModeEnabled: false,
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
      performanceModeEnabled: true,
      vectors: [{ lon: 0, lat: 0, u: 1, v: 0 }],
    });

    expect(viewer.entities.remove).toHaveBeenCalledTimes(2);
    expect(viewer.entities.add).toHaveBeenCalledTimes(2);
  });
});

describe('windArrowDensityForCameraHeight', () => {
  it('returns higher density for lower camera heights', () => {
    expect(
      windArrowDensityForCameraHeight({
        cameraHeightMeters: 50_000,
        performanceModeEnabled: false,
      }),
    ).toBe(32);

    expect(
      windArrowDensityForCameraHeight({
        cameraHeightMeters: 600_000,
        performanceModeEnabled: false,
      }),
    ).toBe(20);

    expect(
      windArrowDensityForCameraHeight({
        cameraHeightMeters: 30_000_000,
        performanceModeEnabled: false,
      }),
    ).toBe(4);
  });

  it('reduces density in performance mode and handles missing heights', () => {
    expect(
      windArrowDensityForCameraHeight({
        cameraHeightMeters: 600_000,
        performanceModeEnabled: true,
      }),
    ).toBe(10);

    expect(
      windArrowDensityForCameraHeight({
        cameraHeightMeters: null,
        performanceModeEnabled: false,
      }),
    ).toBe(12);
  });
});

