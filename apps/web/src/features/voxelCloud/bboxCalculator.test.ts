import { describe, expect, it, vi } from 'vitest';

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

import { Math as CesiumMath } from 'cesium';
import { computeLocalModeBBox } from './bboxCalculator';

describe('computeLocalModeBBox', () => {
  it('returns a bounded 3D bbox around the camera', () => {
    const camera = {
      positionCartographic: {
        longitude: CesiumMath.toRadians(10),
        latitude: CesiumMath.toRadians(20),
        height: 3000,
      },
      frustum: { fov: CesiumMath.toRadians(60), aspectRatio: 1 },
      positionWC: { x: 0, y: 0, z: 0 },
      directionWC: { x: 0, y: 0, z: 1 },
    } as never;

    const bbox = computeLocalModeBBox(camera);
    expect(bbox.bottom).toBe(0);
    expect(bbox.top).toBe(12000);
    expect(bbox.west).toBeLessThan(bbox.east);
    expect(bbox.south).toBeLessThan(bbox.north);
    expect((bbox.west + bbox.east) / 2).toBeCloseTo(10, 1);
    expect((bbox.south + bbox.north) / 2).toBeCloseTo(20, 1);
  });
});

