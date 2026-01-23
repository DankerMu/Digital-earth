import { describe, expect, it } from 'vitest';

import { recommendVoxelCloudParams } from './recommendations';

describe('recommendVoxelCloudParams', () => {
  it('falls back when dimensions are missing', () => {
    const rec = recommendVoxelCloudParams({
      volumeShape: [64, 64, 64],
      dimensionsMeters: null,
    });

    expect(rec.stepVoxels).toBe(1);
    expect(rec.stepMeters).toBeNull();
    expect(rec.maxSteps).toBe(128);
  });

  it('computes step size from voxel resolution and diagonal', () => {
    const rec = recommendVoxelCloudParams({
      volumeShape: [64, 64, 64],
      dimensionsMeters: { width: 6400, height: 6400, depth: 6400 },
      targetMaxSteps: 128,
    });

    expect(rec.maxSteps).toBe(128);
    expect(rec.stepVoxels).toBeGreaterThanOrEqual(1);
    expect(rec.stepMeters).not.toBeNull();
    expect(rec.stepMeters!).toBeGreaterThan(0);
  });

  it('clamps targetMaxSteps and rounds values', () => {
    const rec = recommendVoxelCloudParams({
      volumeShape: [64, 64, 64],
      dimensionsMeters: { width: 6400, height: 6400, depth: 6400 },
      targetMaxSteps: 9999,
    });

    expect(rec.maxSteps).toBe(512);
    expect(rec.stepVoxels).toBeLessThanOrEqual(4);
  });
});

