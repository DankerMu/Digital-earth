import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => {
  const computeLocalModeBBox = vi.fn(() => ({
    west: 0,
    south: 0,
    east: 1,
    north: 1,
    bottom: 0,
    top: 12000,
  }));

  const fetchVolumePack = vi.fn();
  const loadFromArrayBuffer = vi.fn(async () => {});
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
    mocks.fetchVolumePack.mockReset();
  });

  it('caches and reuses volume responses', async () => {
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
