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
  const loadFromArrayBuffer = vi.fn(async (_buffer: ArrayBuffer, _options?: { signal?: AbortSignal }) => {});
  const setEnabled = vi.fn();
  const destroy = vi.fn();

  const VoxelCloudRenderer = vi.fn(function () {
    return {
      loadFromArrayBuffer,
      setEnabled,
      destroy,
    };
  });

  return {
    defaultBBox,
    computeLocalModeBBox,
    fetchVolumePack,
    loadFromArrayBuffer,
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
    mocks.loadFromArrayBuffer.mockImplementation(async (_buffer: ArrayBuffer, _options?: { signal?: AbortSignal }) => {});
  });

  it('caches and skips reloads when camera stays stable', async () => {
    const viewer = makeViewer();
    mocks.fetchVolumePack.mockResolvedValueOnce(new ArrayBuffer(4));

    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300, 500],
      res: 1000,
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
      res: 1000,
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

    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300],
      res: 1000,
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
    mocks.loadFromArrayBuffer.mockImplementation(async () => {});
    await layer.updateForCamera({} as never);
    expect(mocks.loadFromArrayBuffer).toHaveBeenCalledTimes(2);
  });

  it('disables the renderer on fetch failure (fallback)', async () => {
    const viewer = makeViewer();
    mocks.fetchVolumePack.mockRejectedValueOnce(new Error('boom'));

    const layer = new VoxelCloudLayer(viewer as never, {
      apiBaseUrl: 'http://api.test',
      levels: [300],
      res: 1000,
    });

    await layer.updateForCamera({} as never);

    expect(mocks.setEnabled).toHaveBeenCalledWith(false);
  });
});
