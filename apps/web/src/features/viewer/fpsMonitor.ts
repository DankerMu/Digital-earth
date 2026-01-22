export type FpsMonitorSnapshot = {
  fps: number | null;
  lastFrameAtMs: number | null;
};

export type FpsMonitor = {
  recordFrame: (nowMs: number) => number | null;
  getSnapshot: () => FpsMonitorSnapshot;
  reset: () => void;
};

export type FpsMonitorOptions = {
  sampleWindowMs?: number;
  idleResetMs?: number;
};

function normalizePositiveInt(value: unknown, fallback: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return fallback;
  const rounded = Math.round(value);
  return rounded > 0 ? rounded : fallback;
}

export function createFpsMonitor(options: FpsMonitorOptions = {}): FpsMonitor {
  const sampleWindowMs = normalizePositiveInt(options.sampleWindowMs, 1000);
  const idleResetMs = normalizePositiveInt(options.idleResetMs, Math.max(2000, sampleWindowMs));

  let fps: number | null = null;
  let lastFrameAtMs: number | null = null;
  let windowStartMs = 0;
  let frames = 0;

  const reset = () => {
    fps = null;
    lastFrameAtMs = null;
    windowStartMs = 0;
    frames = 0;
  };

  const recordFrame = (nowMs: number) => {
    if (typeof nowMs !== 'number' || !Number.isFinite(nowMs)) return fps;

    if (lastFrameAtMs != null && nowMs - lastFrameAtMs > idleResetMs) {
      fps = null;
      frames = 0;
      windowStartMs = nowMs;
    }

    lastFrameAtMs = nowMs;

    if (frames === 0) {
      windowStartMs = nowMs;
    }
    frames += 1;

    const delta = nowMs - windowStartMs;
    if (delta < sampleWindowMs) return fps;

    const computed = delta > 0 ? Math.round((frames * 1000) / delta) : null;
    fps = typeof computed === 'number' && Number.isFinite(computed) ? computed : null;
    frames = 0;
    windowStartMs = nowMs;
    return fps;
  };

  return {
    recordFrame,
    getSnapshot: () => ({ fps, lastFrameAtMs }),
    reset,
  };
}

export type LowFpsDetector = {
  recordSample: (options: { fps: number | null; nowMs: number }) => boolean;
  reset: () => void;
};

export type LowFpsDetectorOptions = {
  thresholdFps?: number;
  consecutiveSamples?: number;
  cooldownMs?: number;
};

export function createLowFpsDetector(options: LowFpsDetectorOptions = {}): LowFpsDetector {
  const thresholdFps = normalizePositiveInt(options.thresholdFps, 30);
  const consecutiveSamples = normalizePositiveInt(options.consecutiveSamples, 3);
  const cooldownMs = normalizePositiveInt(options.cooldownMs, 60_000);

  let lowCount = 0;
  let lastSuggestedAtMs = -Infinity;

  const reset = () => {
    lowCount = 0;
    lastSuggestedAtMs = -Infinity;
  };

  const recordSample = (sample: { fps: number | null; nowMs: number }) => {
    const nowMs = sample.nowMs;
    if (typeof nowMs !== 'number' || !Number.isFinite(nowMs)) return false;

    if (nowMs - lastSuggestedAtMs < cooldownMs) {
      return false;
    }

    const fps = sample.fps;
    if (typeof fps !== 'number' || !Number.isFinite(fps)) {
      lowCount = 0;
      return false;
    }

    if (fps < thresholdFps) {
      lowCount += 1;
    } else {
      lowCount = 0;
      return false;
    }

    if (lowCount < consecutiveSamples) return false;

    lastSuggestedAtMs = nowMs;
    lowCount = 0;
    return true;
  };

  return { recordSample, reset };
}

