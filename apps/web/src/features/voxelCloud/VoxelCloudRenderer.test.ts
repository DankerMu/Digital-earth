import * as zstd from '@mongodb-js/zstd';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('cesium', () => {
  class Cartesian2 {
    x: number;
    y: number;
    constructor(x = 0, y = 0) {
      this.x = x;
      this.y = y;
    }
  }

  class Cartesian3 {
    x: number;
    y: number;
    z: number;
    constructor(x = 0, y = 0, z = 0) {
      this.x = x;
      this.y = y;
      this.z = z;
    }

    static fromDegrees(lon: number, lat: number, height = 0) {
      return new Cartesian3(lon, lat, height);
    }

    static distance(a: Cartesian3, b: Cartesian3) {
      return Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
    }

    static ZERO = new Cartesian3(0, 0, 0);
    static UNIT_X = new Cartesian3(1, 0, 0);
    static UNIT_Y = new Cartesian3(0, 1, 0);
    static UNIT_Z = new Cartesian3(0, 0, 1);
  }

  class PostProcessStage {
    enabled = true;
    options: unknown;
    constructor(options: unknown) {
      this.options = options;
    }
    destroy() {
      // noop
    }
  }

  const Transforms = {
    eastNorthUpToFixedFrame: vi.fn(() => [
      1, 0, 0, 0,
      0, 1, 0, 0,
      0, 0, 1, 0,
      0, 0, 0, 1,
    ]),
  };

  const CesiumMath = {
    toRadians: (deg: number) => (deg * Math.PI) / 180,
    toDegrees: (rad: number) => (rad * 180) / Math.PI,
    negativePiToPi: (rad: number) => {
      const twoPi = Math.PI * 2;
      let v = ((rad % twoPi) + twoPi) % twoPi;
      if (v > Math.PI) v -= twoPi;
      return v;
    },
  };

  return {
    Cartesian2,
    Cartesian3,
    PostProcessStage,
    Transforms,
    Math: CesiumMath,
  };
});

import { VoxelCloudRenderer } from './index';

function encodeHeader(header: object): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(header));
}

async function buildPack(header: object, bodyRaw: Uint8Array): Promise<Uint8Array> {
  const headerBytes = encodeHeader(header);
  const headerLen = headerBytes.byteLength;

  const bodyCompressed = await zstd.compress(Buffer.from(bodyRaw));
  const out = new Uint8Array(8 + headerLen + bodyCompressed.byteLength);

  out.set([0x56, 0x4f, 0x4c, 0x50], 0); // "VOLP"
  new DataView(out.buffer).setUint32(4, headerLen, true);
  out.set(headerBytes, 8);
  out.set(bodyCompressed, 8 + headerLen);
  return out;
}

function makeViewer() {
  return {
    scene: {
      postProcessStages: {
        add: vi.fn(),
        remove: vi.fn(),
      },
      requestRender: vi.fn(),
    },
  };
}

describe('VoxelCloudRenderer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('loads a volume pack, builds an atlas, and adds a post-process stage', async () => {
    const getContext = vi.fn(() => ({ putImageData: vi.fn() }));
    (HTMLCanvasElement.prototype.getContext as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      getContext as unknown as HTMLCanvasElement['getContext'],
    );

    const shape: [number, number, number] = [2, 2, 2];
    const header = {
      version: 1,
      bbox: { west: 0, south: 0, east: 1, north: 1, bottom: 0, top: 10 },
      shape,
      dtype: 'uint8',
      scale: 1 / 255,
      offset: 0,
      compression: 'zstd',
    };

    const bodyRaw = Uint8Array.from([0, 10, 20, 30, 40, 50, 60, 70]);
    const pack = await buildPack(header, bodyRaw);

    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      arrayBuffer: async () => pack.buffer.slice(pack.byteOffset, pack.byteOffset + pack.byteLength),
    }));
    vi.stubGlobal('fetch', fetchMock);

    const viewer = makeViewer();
    const renderer = new VoxelCloudRenderer(viewer as never, { enabled: true });

    await renderer.loadFromUrl('http://test/volume.volp');
    const snapshot = renderer.getSnapshot();

    expect(snapshot.ready).toBe(true);
    expect(snapshot.volume?.shape).toEqual([2, 2, 2]);
    expect(snapshot.metrics?.bytes).toBe(pack.byteLength);
    expect(viewer.scene.postProcessStages.add).toHaveBeenCalledTimes(1);

    renderer.destroy();
    expect(viewer.scene.postProcessStages.remove).toHaveBeenCalledTimes(1);
  });

  it('supports AbortSignal cancellation without setting lastError', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      arrayBuffer: async () => new ArrayBuffer(0),
    }));
    vi.stubGlobal('fetch', fetchMock);

    const viewer = makeViewer();
    const renderer = new VoxelCloudRenderer(viewer as never, { enabled: true });

    const controller = new AbortController();
    controller.abort();

    await expect(
      renderer.loadFromUrl('http://test/volume.volp', { signal: controller.signal }),
    ).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(renderer.getSnapshot().lastError).toBeNull();
  });

  it('throws when bbox is missing', async () => {
    const getContext = vi.fn(() => ({ putImageData: vi.fn() }));
    (HTMLCanvasElement.prototype.getContext as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      getContext as unknown as HTMLCanvasElement['getContext'],
    );

    const shape: [number, number, number] = [1, 1, 1];
    const header = {
      version: 1,
      shape,
      dtype: 'uint8',
      scale: 1 / 255,
      offset: 0,
      compression: 'zstd',
    };

    const pack = await buildPack(header, Uint8Array.from([0]));
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      arrayBuffer: async () => pack.buffer.slice(pack.byteOffset, pack.byteOffset + pack.byteLength),
    })));

    const viewer = makeViewer();
    const renderer = new VoxelCloudRenderer(viewer as never, { enabled: true });

    await expect(renderer.loadFromUrl('http://test/volume.volp')).rejects.toThrow(/bbox/i);
  });

  it('throws when postProcessStages are unavailable', async () => {
    const getContext = vi.fn(() => ({ putImageData: vi.fn() }));
    (HTMLCanvasElement.prototype.getContext as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      getContext as unknown as HTMLCanvasElement['getContext'],
    );

    const shape: [number, number, number] = [1, 1, 1];
    const header = {
      version: 1,
      bbox: { west: 0, south: 0, east: 1, north: 1, bottom: 0, top: 10 },
      shape,
      dtype: 'uint8',
      scale: 1 / 255,
      offset: 0,
      compression: 'zstd',
    };

    const pack = await buildPack(header, Uint8Array.from([0]));
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      arrayBuffer: async () => pack.buffer.slice(pack.byteOffset, pack.byteOffset + pack.byteLength),
    })));

    const viewer = {
      scene: {
        requestRender: vi.fn(),
      },
    };
    const renderer = new VoxelCloudRenderer(viewer as never, { enabled: true });

    await expect(renderer.loadFromUrl('http://test/volume.volp')).rejects.toThrow(/postProcessStages/i);
  });
});
