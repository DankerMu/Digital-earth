import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => {
  const defaultBBox = {
    west: 0,
    south: 0,
    east: 1,
    north: 1,
    bottom: 0,
    top: 12000,
  };

  const computeLocalModeBBox = vi.fn(() => ({
    ...defaultBBox,
  }));

  const fetchVolumePack = vi.fn();
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const loadFromArrayBuffer = vi.fn(async (_buffer: ArrayBuffer, _options?: { signal?: AbortSignal }) => {});
  const setRaySteps = vi.fn();
  const setEnabled = vi.fn();
  const destroy = vi.fn();

  const VoxelCloudRenderer = vi.fn(function () {
    return {
      loadFromArrayBuffer,
      setRaySteps,
      setEnabled,
      destroy,
    };
  });

  return {
    defaultBBox,
    computeLocalModeBBox,
    fetchVolumePack,
    loadFromArrayBuffer,
    setRaySteps,
    setEnabled,
    destroy,
    VoxelCloudRenderer,
  };
});

vi.mock('./bboxCalculator', () => ({
  computeLocalModeBBox: mocks.computeLocalModeBBox,
}));

vi.mock('./volumeApi', () => ({
  fetchVolumePack: mocks.fetchVolumePack,
}));

vi.mock('./VoxelCloudRenderer', () => ({
  VoxelCloudRenderer: mocks.VoxelCloudRenderer,
}));

import { VoxelCloudLayer } from './VoxelCloudLayer';

function makeViewer() {
  return {
    scene: {
      requestRender: vi.fn(),
    },
  };
}

describe('VoxelCloudLayer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.computeLocalModeBBox.mockImplementation(() => ({ ...mocks.defaultBBox }));
    mocks.fetchVolumePack.mockReset();
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    mocks.loadFromArrayBuffer.mockImplementation(async (_buffer: ArrayBuffer, _options?: { signal?: AbortSignal }) => {});
  });

  it('caches and skips reloads when camera stays stable', async () => {
    const viewer = makeViewer();
    mocks.fetchVolumePack.mockResolvedValueOnce(new ArrayBuffer(4));

    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300, 500],
      cacheEntries: 4,
    });

    await layer.updateForCamera({} as never);
    await layer.updateForCamera({} as never);

    expect(mocks.fetchVolumePack).toHaveBeenCalledTimes(1);
    expect(mocks.loadFromArrayBuffer).toHaveBeenCalledTimes(1);
  });

  it('clears lastLoadedKey when activating fallback', async () => {
    const viewer = makeViewer();
    const volume = new ArrayBuffer(4);
    mocks.fetchVolumePack.mockResolvedValueOnce(volume);

    const options = {
      apiBaseUrl: 'http://api.test',
      levels: [300],
      cacheEntries: 4,
    };

    const layer = new VoxelCloudLayer(viewer as never, options);
    mocks.setEnabled.mockClear();

    await layer.updateForCamera({} as never);
    expect(mocks.fetchVolumePack).toHaveBeenCalledTimes(1);
    expect(mocks.loadFromArrayBuffer).toHaveBeenCalledTimes(1);

    options.apiBaseUrl = '';
    await layer.updateForCamera({} as never);
    expect(mocks.setEnabled).toHaveBeenCalledWith(false);

    options.apiBaseUrl = 'http://api.test';
    await layer.updateForCamera({} as never);
    expect(mocks.fetchVolumePack).toHaveBeenCalledTimes(1);
    expect(mocks.loadFromArrayBuffer).toHaveBeenCalledTimes(2);
    expect(mocks.setEnabled.mock.calls.at(-1)).toEqual([true]);
  });

  it('aborts stale cached reloads and prevents state updates', async () => {
    const viewer = makeViewer();
    const volumeA = new ArrayBuffer(4);
    const volumeB = new ArrayBuffer(8);

    const bboxA = { ...mocks.defaultBBox };
    const bboxB = { ...mocks.defaultBBox, west: 5, east: 6 };

    mocks.computeLocalModeBBox
      .mockReturnValueOnce(bboxA)
      .mockReturnValueOnce(bboxB)
      .mockReturnValueOnce(bboxA)
      .mockReturnValueOnce(bboxB);

    mocks.fetchVolumePack.mockResolvedValueOnce(volumeA).mockResolvedValueOnce(volumeB);

    const nowMock = vi.spyOn(performance, 'now');
    nowMock
      .mockReturnValueOnce(0)
      .mockReturnValueOnce(600)
      .mockReturnValue(1200);

    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300],
      cacheEntries: 4,
    });

    await layer.updateForCamera({} as never); // fetch A (cache miss)
    await layer.updateForCamera({} as never); // fetch B (cache miss)

    mocks.setEnabled.mockClear();
    mocks.loadFromArrayBuffer.mockClear();

    let resolveLoad!: () => void;
    let capturedSignal: AbortSignal | undefined;
    const cachedLoad = new Promise<void>((resolve) => {
      resolveLoad = () => resolve();
    });

    mocks.loadFromArrayBuffer.mockImplementation(async (_buffer: ArrayBuffer, options?: { signal?: AbortSignal }) => {
      capturedSignal = options?.signal;
      return cachedLoad;
    });

    const pending = layer.updateForCamera({} as never); // cached reload A (in-flight)
    await layer.updateForCamera({} as never); // camera back to already-loaded B, should abort A reload

    expect(capturedSignal).toBeDefined();
    expect(capturedSignal?.aborted).toBe(true);

    resolveLoad();
    await pending;

    expect(mocks.setEnabled).not.toHaveBeenCalled();

    mocks.computeLocalModeBBox.mockReturnValueOnce(bboxA);
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    mocks.loadFromArrayBuffer.mockImplementation(async (_buffer: ArrayBuffer, _options?: { signal?: AbortSignal }) => {});
    await layer.updateForCamera({} as never);
    expect(mocks.loadFromArrayBuffer).toHaveBeenCalledTimes(2);

    nowMock.mockRestore();
  });

  it('disables the renderer on fetch failure (fallback)', async () => {
    const viewer = makeViewer();
    mocks.fetchVolumePack.mockRejectedValueOnce(new Error('boom'));

    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300],
    });

    await layer.updateForCamera({} as never);

    expect(mocks.setEnabled).toHaveBeenCalledWith(false);
  });

  it('falls back when cached reload fails', async () => {
    const viewer = makeViewer();
    const volumeA = new ArrayBuffer(4);
    const volumeB = new ArrayBuffer(8);

    const bboxA = { ...mocks.defaultBBox };
    const bboxB = { ...mocks.defaultBBox, west: 5, east: 6 };
    mocks.computeLocalModeBBox.mockReturnValueOnce(bboxA).mockReturnValueOnce(bboxB).mockReturnValueOnce(bboxA);

    mocks.fetchVolumePack.mockResolvedValueOnce(volumeA).mockResolvedValueOnce(volumeB);

    const nowMock = vi.spyOn(performance, 'now');
    nowMock
      .mockReturnValueOnce(0)
      .mockReturnValueOnce(600)
      .mockReturnValue(1200);

    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300],
    });

    await layer.updateForCamera({} as never); // fetch A
    await layer.updateForCamera({} as never); // fetch B

    mocks.setEnabled.mockClear();
    mocks.loadFromArrayBuffer.mockRejectedValueOnce(new Error('bad cached volume'));

    await layer.updateForCamera({} as never); // cached reload A -> error -> fallback

    expect(mocks.fetchVolumePack).toHaveBeenCalledTimes(2);
    expect(mocks.setEnabled).toHaveBeenCalledWith(false);

    nowMock.mockRestore();
  });

  it('uses quality presets for res and ray steps', async () => {
    const viewer = makeViewer();
    mocks.fetchVolumePack.mockResolvedValueOnce(new ArrayBuffer(4)).mockResolvedValueOnce(new ArrayBuffer(8));

    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300],
      quality: 'high',
    });

    expect(mocks.setRaySteps).toHaveBeenCalledWith(128);

    await layer.updateForCamera({} as never);
    expect(mocks.fetchVolumePack).toHaveBeenCalledWith(expect.objectContaining({ res: 1000 }), expect.anything());

    layer.setQuality('low');
    expect(mocks.setRaySteps).toHaveBeenCalledWith(32);

    await layer.updateForCamera({} as never);
    expect(mocks.fetchVolumePack).toHaveBeenCalledWith(expect.objectContaining({ res: 4000 }), expect.anything());
  });

  it('resets the performance monitor when disabling autoDowngrade', () => {
    const viewer = makeViewer();
    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300],
      quality: 'high',
      autoDowngrade: true,
    });

    for (let i = 0; i < 29; i += 1) {
      layer.recordFrame(1000 / 20);
    }

    layer.setAutoDowngrade(false);
    layer.setAutoDowngrade(true);
    layer.recordFrame(1000 / 20);

    expect(layer.quality).toBe('high');
  });

  it('auto-downgrades and upgrades quality based on sustained FPS', () => {
    const viewer = makeViewer();
    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300],
      quality: 'high',
      autoDowngrade: true,
    });

    mocks.setRaySteps.mockClear();

    for (let i = 0; i < 30; i += 1) {
      layer.recordFrame(1000 / 20);
    }

    expect(layer.quality).toBe('medium');
    expect(mocks.setRaySteps).toHaveBeenCalledWith(64);

    for (let i = 0; i < 30; i += 1) {
      layer.recordFrame(1000 / 60);
    }

    expect(layer.quality).toBe('high');
    expect(mocks.setRaySteps).toHaveBeenCalledWith(128);
  });

  it('does not auto-adjust quality when autoDowngrade is disabled', () => {
    const viewer = makeViewer();
    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300],
      quality: 'high',
      autoDowngrade: false,
    });

    for (let i = 0; i < 60; i += 1) {
      layer.recordFrame(1000 / 10);
    }

    expect(layer.quality).toBe('high');
  });

  it('throttles API calls based on preset updateInterval', async () => {
    const viewer = makeViewer();

    const bboxA = { ...mocks.defaultBBox };
    const bboxB = { ...mocks.defaultBBox, west: 5, east: 6 };
    mocks.computeLocalModeBBox.mockReturnValueOnce(bboxA).mockReturnValueOnce(bboxB);

    let resolveFetch!: (buffer: ArrayBuffer) => void;
    let capturedSignal: AbortSignal | undefined;
    const fetchPromise = new Promise<ArrayBuffer>((resolve) => {
      resolveFetch = (buffer) => resolve(buffer);
    });

    mocks.fetchVolumePack.mockImplementation(async (_params: unknown, options?: { signal?: AbortSignal }) => {
      capturedSignal = options?.signal;
      return fetchPromise;
    });

    const nowMock = vi.spyOn(performance, 'now');
    nowMock
      .mockReturnValueOnce(0)
      .mockReturnValueOnce(100)
      .mockReturnValue(1000);

    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300],
      quality: 'high',
    });

    const pending = layer.updateForCamera({} as never);
    await layer.updateForCamera({} as never);

    expect(mocks.fetchVolumePack).toHaveBeenCalledTimes(1);
    expect(capturedSignal?.aborted).toBe(true);

    resolveFetch(new ArrayBuffer(4));
    await pending;

    nowMock.mockRestore();
  });

  it('records frames from viewer postRender when available', () => {
    const listeners: Array<() => void> = [];
    const viewer = {
      scene: {
        requestRender: vi.fn(),
        postRender: {
          addEventListener: vi.fn((listener: () => void) => listeners.push(listener)),
          removeEventListener: vi.fn((listener: () => void) => {
            const index = listeners.indexOf(listener);
            if (index >= 0) listeners.splice(index, 1);
          }),
        },
      },
    };

    const nowMock = vi.spyOn(performance, 'now');
    nowMock
      .mockReturnValueOnce(0)
      .mockReturnValueOnce(16.666)
      .mockReturnValue(33.333);

    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300],
    });

    const recordSpy = vi.spyOn(layer, 'recordFrame');

    expect(viewer.scene.postRender.addEventListener).toHaveBeenCalledTimes(1);
    expect(listeners).toHaveLength(1);

    listeners[0]?.();
    expect(recordSpy).not.toHaveBeenCalled();

    listeners[0]?.();
    expect(recordSpy).toHaveBeenCalledTimes(1);
    expect(recordSpy.mock.calls[0]?.[0]).toBeCloseTo(16.666, 2);

    layer.destroy();
    expect(viewer.scene.postRender.removeEventListener).toHaveBeenCalledTimes(1);

    nowMock.mockRestore();
  });

  it('supports quality and autoDowngrade property accessors', () => {
    const viewer = makeViewer();
    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300],
      quality: 'high',
    });

    expect(layer.quality).toBe('high');
    layer.quality = 'high';

    layer.autoDowngrade = true;
    expect(layer.autoDowngrade).toBe(true);
  });

  it('skips duplicate fetches while the same camera key is in-flight', async () => {
    const viewer = makeViewer();
    let resolveFetch!: (buffer: ArrayBuffer) => void;
    const fetchPromise = new Promise<ArrayBuffer>((resolve) => {
      resolveFetch = (buffer) => resolve(buffer);
    });

    mocks.fetchVolumePack.mockReturnValue(fetchPromise);

    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300],
    });

    const pending = layer.updateForCamera({} as never);
    await layer.updateForCamera({} as never);

    expect(mocks.fetchVolumePack).toHaveBeenCalledTimes(1);

    resolveFetch(new ArrayBuffer(4));
    await pending;
  });

  it('includes validTime in Volume API requests', async () => {
    const viewer = makeViewer();
    mocks.fetchVolumePack.mockResolvedValueOnce(new ArrayBuffer(4));

    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300],
      validTime: '2024-01-01T00:00:00Z',
    });

    await layer.updateForCamera({} as never);
    expect(mocks.fetchVolumePack).toHaveBeenCalledWith(
      expect.objectContaining({ validTime: '2024-01-01T00:00:00Z' }),
      expect.anything(),
    );
  });

  it('does not re-activate fallback when already active', async () => {
    const viewer = makeViewer();
    const options = {
      apiBaseUrl: '',
      levels: [300],
    };

    const layer = new VoxelCloudLayer(viewer as never, options);
    mocks.setEnabled.mockClear();

    await layer.updateForCamera({} as never);
    await layer.updateForCamera({} as never);

    expect(mocks.setEnabled).toHaveBeenCalledTimes(1);
    expect(mocks.setEnabled).toHaveBeenCalledWith(false);
  });

  it('skips duplicate cached reloads while a cached load is in-flight', async () => {
    const viewer = makeViewer();
    const volume = new ArrayBuffer(4);
    mocks.fetchVolumePack.mockResolvedValueOnce(volume);

    const options = {
      apiBaseUrl: 'http://api.test',
      levels: [300],
    };

    const layer = new VoxelCloudLayer(viewer as never, options);
    await layer.updateForCamera({} as never);

    options.apiBaseUrl = '';
    await layer.updateForCamera({} as never);

    options.apiBaseUrl = 'http://api.test';

    let resolveLoad!: () => void;
    const cachedLoad = new Promise<void>((resolve) => {
      resolveLoad = () => resolve();
    });
    mocks.loadFromArrayBuffer.mockImplementation(async () => cachedLoad);
    mocks.loadFromArrayBuffer.mockClear();

    const pending = layer.updateForCamera({} as never);
    await layer.updateForCamera({} as never);

    expect(mocks.loadFromArrayBuffer).toHaveBeenCalledTimes(1);

    resolveLoad();
    await pending;
  });

  it('treats AbortError during cached reload as cancellation', async () => {
    const viewer = makeViewer();
    const volume = new ArrayBuffer(4);
    mocks.fetchVolumePack.mockResolvedValueOnce(volume);

    const options = {
      apiBaseUrl: 'http://api.test',
      levels: [300],
    };

    const layer = new VoxelCloudLayer(viewer as never, options);
    await layer.updateForCamera({} as never);

    options.apiBaseUrl = '';
    await layer.updateForCamera({} as never);

    mocks.setEnabled.mockClear();
    mocks.loadFromArrayBuffer.mockRejectedValueOnce(new DOMException('aborted', 'AbortError'));

    options.apiBaseUrl = 'http://api.test';
    await layer.updateForCamera({} as never);

    expect(mocks.setEnabled).not.toHaveBeenCalled();
  });

  it('treats AbortError during fetch as cancellation', async () => {
    const viewer = makeViewer();
    mocks.fetchVolumePack.mockRejectedValueOnce(new DOMException('aborted', 'AbortError'));

    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300],
    });
    mocks.setEnabled.mockClear();

    await layer.updateForCamera({} as never);
    expect(mocks.setEnabled).not.toHaveBeenCalled();
  });

  it('aborts in-flight requests on destroy', async () => {
    const viewer = makeViewer();
    let resolveFetch!: (buffer: ArrayBuffer) => void;
    let capturedSignal: AbortSignal | undefined;
    const fetchPromise = new Promise<ArrayBuffer>((resolve) => {
      resolveFetch = (buffer) => resolve(buffer);
    });

    mocks.fetchVolumePack.mockImplementation(async (_params: unknown, options?: { signal?: AbortSignal }) => {
      capturedSignal = options?.signal;
      return fetchPromise;
    });

    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300],
    });

    const pending = layer.updateForCamera({} as never);
    layer.destroy();

    expect(capturedSignal).toBeDefined();
    expect(capturedSignal?.aborted).toBe(true);

    resolveFetch(new ArrayBuffer(4));
    await pending;
  });

  it('auto-downgrades from medium to low', () => {
    const viewer = makeViewer();
    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300],
      quality: 'medium',
      autoDowngrade: true,
    });

    mocks.setRaySteps.mockClear();

    for (let i = 0; i < 30; i += 1) {
      layer.recordFrame(1000 / 20);
    }

    expect(layer.quality).toBe('low');
    expect(mocks.setRaySteps).toHaveBeenCalledWith(32);
  });

  it('auto-upgrades from low to medium', () => {
    const viewer = makeViewer();
    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300],
      quality: 'low',
      autoDowngrade: true,
    });

    mocks.setRaySteps.mockClear();

    for (let i = 0; i < 30; i += 1) {
      layer.recordFrame(1000 / 60);
    }

    expect(layer.quality).toBe('medium');
    expect(mocks.setRaySteps).toHaveBeenCalledWith(64);
  });
});
