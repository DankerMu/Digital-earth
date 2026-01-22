import { describe, expect, it } from 'vitest';

import { createFpsMonitor, createLowFpsDetector } from './fpsMonitor';

describe('createFpsMonitor', () => {
  it('computes fps over the sample window', () => {
    const monitor = createFpsMonitor({ sampleWindowMs: 1000, idleResetMs: 5000 });

    expect(monitor.recordFrame(0)).toBeNull();
    expect(monitor.recordFrame(500)).toBeNull();
    expect(monitor.recordFrame(1000)).toBe(2);

    const snapshot = monitor.getSnapshot();
    expect(snapshot.fps).toBe(2);
    expect(snapshot.lastFrameAtMs).toBe(1000);
  });

  it('does not overestimate fps by counting the window start frame', () => {
    const monitor = createFpsMonitor({ sampleWindowMs: 1000, idleResetMs: 5000 });

    // Simulate 60fps over a 1s window: 61 frames at timestamps [0..1000].
    for (let index = 0; index < 60; index += 1) {
      expect(monitor.recordFrame((index * 1000) / 60)).toBeNull();
    }

    expect(monitor.recordFrame(1000)).toBe(60);
    expect(monitor.getSnapshot().fps).toBe(60);
  });

  it('resets fps after an idle gap', () => {
    const monitor = createFpsMonitor({ sampleWindowMs: 1000, idleResetMs: 2000 });

    monitor.recordFrame(0);
    monitor.recordFrame(500);
    monitor.recordFrame(1000);
    expect(monitor.getSnapshot().fps).toBe(2);

    // Next frame arrives after a long pause: treat as idle and reset.
    expect(monitor.recordFrame(4000)).toBeNull();
    expect(monitor.getSnapshot().fps).toBeNull();
  });
});

describe('createLowFpsDetector', () => {
  it('suggests after consecutive low samples and respects cooldown', () => {
    const detector = createLowFpsDetector({
      thresholdFps: 30,
      consecutiveSamples: 2,
      cooldownMs: 60_000,
    });

    expect(detector.recordSample({ fps: 29, nowMs: 0 })).toBe(false);
    expect(detector.recordSample({ fps: 28, nowMs: 1000 })).toBe(true);

    // Cooldown blocks repeated suggestions.
    expect(detector.recordSample({ fps: 20, nowMs: 2000 })).toBe(false);
    expect(detector.recordSample({ fps: 20, nowMs: 61_000 })).toBe(false);
    expect(detector.recordSample({ fps: 20, nowMs: 62_000 })).toBe(true);
  });

  it('resets the counter when fps recovers or data is missing', () => {
    const detector = createLowFpsDetector({ thresholdFps: 30, consecutiveSamples: 2, cooldownMs: 1 });

    expect(detector.recordSample({ fps: 29, nowMs: 0 })).toBe(false);
    expect(detector.recordSample({ fps: 31, nowMs: 1 })).toBe(false);

    expect(detector.recordSample({ fps: 29, nowMs: 2 })).toBe(false);
    expect(detector.recordSample({ fps: null, nowMs: 3 })).toBe(false);
    expect(detector.recordSample({ fps: 29, nowMs: 4 })).toBe(false);
  });
});
