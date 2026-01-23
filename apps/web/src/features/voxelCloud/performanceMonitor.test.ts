import { describe, expect, it } from 'vitest';

import { VoxelCloudPerformanceMonitor } from './performanceMonitor';

describe('VoxelCloudPerformanceMonitor', () => {
  it('computes average FPS from frame deltas', () => {
    const monitor = new VoxelCloudPerformanceMonitor();

    for (let i = 0; i < 30; i += 1) {
      monitor.recordFrame(1000 / 60);
    }

    expect(monitor.getCurrentFps()).toBeGreaterThan(59);
    expect(monitor.getCurrentFps()).toBeLessThan(61);
    expect(monitor.shouldUpgrade()).toBe(true);
    expect(monitor.shouldDowngrade()).toBe(false);
  });

  it('requires a sustained history before triggering downgrade/upgrade', () => {
    const monitor = new VoxelCloudPerformanceMonitor();

    for (let i = 0; i < 10; i += 1) {
      monitor.recordFrame(1000 / 20);
    }

    expect(monitor.getCurrentFps()).toBeGreaterThan(0);
    expect(monitor.shouldDowngrade()).toBe(false);
    expect(monitor.shouldUpgrade()).toBe(false);
  });

  it('triggers downgrade when sustained FPS is below the threshold', () => {
    const monitor = new VoxelCloudPerformanceMonitor();

    for (let i = 0; i < 30; i += 1) {
      monitor.recordFrame(1000 / 20);
    }

    expect(monitor.getCurrentFps()).toBeGreaterThan(19);
    expect(monitor.getCurrentFps()).toBeLessThan(21);
    expect(monitor.shouldDowngrade()).toBe(true);
    expect(monitor.shouldUpgrade()).toBe(false);
  });

  it('ignores invalid frame deltas', () => {
    const monitor = new VoxelCloudPerformanceMonitor();

    monitor.recordFrame(Number.NaN);
    monitor.recordFrame(-5);
    monitor.recordFrame(0);
    monitor.recordFrame(Number.MIN_VALUE);

    expect(monitor.getCurrentFps()).toBe(0);
    expect(monitor.shouldDowngrade()).toBe(false);
    expect(monitor.shouldUpgrade()).toBe(false);
  });
});
