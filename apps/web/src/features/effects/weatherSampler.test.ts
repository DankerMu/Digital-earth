import { describe, expect, it, vi } from 'vitest';

import {
  createCloudSampler,
  createWeatherSampler,
  precipitationMmToIntensity,
  temperatureCToPrecipitationKind,
  tileBoundsForXY,
  tileXYForLonLatDegrees,
} from './weatherSampler';

function makeImageData(width: number, height: number, rgba: [number, number, number, number]): ImageData {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < width * height; i += 1) {
    const idx = i * 4;
    data[idx] = rgba[0];
    data[idx + 1] = rgba[1];
    data[idx + 2] = rgba[2];
    data[idx + 3] = rgba[3];
  }
  return { data, width, height } as unknown as ImageData;
}

describe('weatherSampler utils', () => {
  it('maps precipitation (mm) to [0,1] intensity using a saturating curve', () => {
    expect(precipitationMmToIntensity(null)).toBe(0);
    expect(precipitationMmToIntensity(-1)).toBe(0);
    expect(precipitationMmToIntensity(0)).toBe(0);
    expect(precipitationMmToIntensity(1)).toBeGreaterThan(0);
    expect(precipitationMmToIntensity(100)).toBeCloseTo(1, 6);
    expect(precipitationMmToIntensity(10_000)).toBeCloseTo(1, 6);
  });

  it('derives precipitation kind from intensity and temperature', () => {
    expect(temperatureCToPrecipitationKind(0, -5)).toBe('none');
    expect(temperatureCToPrecipitationKind(0.2, null)).toBe('rain');
    expect(temperatureCToPrecipitationKind(0.2, -0.1)).toBe('snow');
    expect(temperatureCToPrecipitationKind(0.2, 0)).toBe('snow');
    expect(temperatureCToPrecipitationKind(0.2, 2)).toBe('rain');
  });

  it('computes tile coordinates and bounds using configurable level-zero tiles', () => {
    const xy = tileXYForLonLatDegrees({
      lon: 0,
      lat: 0,
      zoom: 1,
      levelZeroTilesX: 2,
      levelZeroTilesY: 1,
    });

    expect(xy.x).toBeGreaterThanOrEqual(0);
    expect(xy.y).toBeGreaterThanOrEqual(0);

    const bounds = tileBoundsForXY({
      x: xy.x,
      y: xy.y,
      zoom: 1,
      levelZeroTilesX: 2,
      levelZeroTilesY: 1,
    });

    expect(bounds.west).toBeLessThan(bounds.east);
    expect(bounds.south).toBeLessThan(bounds.north);
    expect(bounds.west).toBeGreaterThanOrEqual(-180);
    expect(bounds.east).toBeLessThanOrEqual(180);
    expect(bounds.south).toBeGreaterThanOrEqual(-90);
    expect(bounds.north).toBeLessThanOrEqual(90);
  });
});

describe('createWeatherSampler', () => {
  it('samples precipitation + temperature at a given lon/lat and infers rain', async () => {
    const sampler = createWeatherSampler({
      zoom: 2,
      precipitation: {
        urlTemplate:
          'http://api.test/api/v1/tiles/cldas/2024011500/precipitation/{z}/{x}/{y}.png',
        tileSize: 4,
      },
      temperature: {
        urlTemplate: 'http://api.test/api/v1/tiles/cldas/2024011500/TMP/{z}/{x}/{y}.png',
        tileSize: 4,
      },
      fetchImageData: async (url: string) => {
        if (url.includes('/precipitation/')) {
          return makeImageData(4, 4, [0x3b, 0x82, 0xf6, 255]); // precipitation stop=25
        }
        return makeImageData(4, 4, [0xef, 0x44, 0x44, 255]); // temperature stop=40
      },
    });

    const sample = await sampler.sample({ lon: 116.391, lat: 39.9075 });

    expect(sample.precipitationMm).toBeCloseTo(25, 3);
    expect(sample.temperatureC).toBeCloseTo(40, 3);
    expect(sample.precipitationIntensity).toBeGreaterThan(0);
    expect(sample.precipitationKind).toBe('rain');
  });

  it('infers snow when temperature is <= 0', async () => {
    const sampler = createWeatherSampler({
      zoom: 2,
      precipitation: {
        urlTemplate:
          'http://api.test/api/v1/tiles/cldas/2024011500/precipitation/{z}/{x}/{y}.png',
        tileSize: 4,
      },
      temperature: {
        urlTemplate: 'http://api.test/api/v1/tiles/cldas/2024011500/TMP/{z}/{x}/{y}.png',
        tileSize: 4,
      },
      fetchImageData: async (url: string) => {
        if (url.includes('/precipitation/')) {
          return makeImageData(4, 4, [0x93, 0xc5, 0xfd, 255]); // precipitation stop=10
        }
        return makeImageData(4, 4, [0xff, 0xff, 0xff, 255]); // temperature stop=0
      },
    });

    const sample = await sampler.sample({ lon: 0, lat: 0 });

    expect(sample.precipitationMm).toBeCloseTo(10, 3);
    expect(sample.temperatureC).toBeCloseTo(0, 3);
    expect(sample.precipitationKind).toBe('snow');
  });

  it('returns intensity 0 and kind none when precipitation pixel is transparent', async () => {
    const sampler = createWeatherSampler({
      zoom: 2,
      precipitation: {
        urlTemplate:
          'http://api.test/api/v1/tiles/cldas/2024011500/precipitation/{z}/{x}/{y}.png',
        tileSize: 4,
      },
      temperature: {
        urlTemplate: 'http://api.test/api/v1/tiles/cldas/2024011500/TMP/{z}/{x}/{y}.png',
        tileSize: 4,
      },
      fetchImageData: async (url: string) => {
        if (url.includes('/precipitation/')) {
          return makeImageData(4, 4, [0, 0, 0, 0]);
        }
        return makeImageData(4, 4, [0x3b, 0x82, 0xf6, 255]);
      },
    });

    const sample = await sampler.sample({ lon: 0, lat: 0 });

    expect(sample.precipitationMm).toBeNull();
    expect(sample.precipitationIntensity).toBe(0);
    expect(sample.precipitationKind).toBe('none');
  });

  it('caches image data per tile url', async () => {
    let calls = 0;
    const sampler = createWeatherSampler({
      zoom: 2,
      precipitation: {
        urlTemplate:
          'http://api.test/api/v1/tiles/cldas/2024011500/precipitation/{z}/{x}/{y}.png',
        tileSize: 4,
      },
      temperature: {
        urlTemplate: 'http://api.test/api/v1/tiles/cldas/2024011500/TMP/{z}/{x}/{y}.png',
        tileSize: 4,
      },
      fetchImageData: async () => {
        calls += 1;
        return makeImageData(4, 4, [0xff, 0xff, 0xff, 255]);
      },
    });

    await sampler.sample({ lon: 1, lat: 1 });
    await sampler.sample({ lon: 1, lat: 1 });

    expect(calls).toBe(2);
  });

  it('loads image data via fetch + createImageBitmap when no fetchImageData is provided', async () => {
    const getContext = vi.fn(() => ({
      drawImage: vi.fn(),
      getImageData: vi.fn(() => makeImageData(4, 4, [0x3b, 0x82, 0xf6, 255])),
    })) as unknown as HTMLCanvasElement['getContext'];

    (HTMLCanvasElement.prototype.getContext as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      getContext,
    );

    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      blob: async () => new Blob(['stub']),
    }));
    const createImageBitmapMock = vi.fn(async () => ({ width: 4, height: 4 }));

    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('createImageBitmap', createImageBitmapMock);

    const sampler = createWeatherSampler({
      zoom: 2,
      precipitation: {
        urlTemplate:
          'http://api.test/api/v1/tiles/cldas/2024011500/precipitation/{z}/{x}/{y}.png',
        tileSize: 4,
      },
      temperature: {
        urlTemplate: 'http://api.test/api/v1/tiles/cldas/2024011500/TMP/{z}/{x}/{y}.png',
        tileSize: 4,
      },
    });

    const sample = await sampler.sample({ lon: 116.391, lat: 39.9075 });

    expect(vi.mocked(fetchMock)).toHaveBeenCalledTimes(2);
    expect(vi.mocked(createImageBitmapMock)).toHaveBeenCalledTimes(2);
    expect(sample.precipitationMm).not.toBeNull();
    expect(sample.temperatureC).not.toBeNull();
  });

  it('falls back to HTMLImageElement decoding when createImageBitmap is unavailable', async () => {
    const drawImage = vi.fn((img: unknown) => {
      void img;
    });

    const getImageData = vi.fn(() => makeImageData(4, 4, [0xff, 0xff, 0xff, 255]));

    (HTMLCanvasElement.prototype.getContext as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (() =>
        ({
          drawImage,
          getImageData,
        }) satisfies Partial<CanvasRenderingContext2D>) as unknown as HTMLCanvasElement['getContext'],
    );

    vi.stubGlobal('createImageBitmap', undefined);

    class FakeImage {
      decoding = '';
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      width = 4;
      height = 4;
      private _src = '';

      get src() {
        return this._src;
      }

      set src(value: string) {
        this._src = value;
        queueMicrotask(() => this.onload?.());
      }
    }

    vi.stubGlobal('Image', FakeImage as unknown as typeof Image);

    const createObjectUrlImpl = (blob: Blob | MediaSource) =>
      (blob as unknown as { __url?: string }).__url ?? 'blob:stub';

    if (typeof URL.createObjectURL === 'function') {
      vi.spyOn(URL, 'createObjectURL').mockImplementation(createObjectUrlImpl);
    } else {
      Object.defineProperty(URL, 'createObjectURL', {
        configurable: true,
        value: vi.fn(createObjectUrlImpl),
      });
    }

    if (typeof URL.revokeObjectURL === 'function') {
      vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    } else {
      Object.defineProperty(URL, 'revokeObjectURL', {
        configurable: true,
        value: vi.fn(() => {}),
      });
    }

    const fetchMock = vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      blob: async () => {
        const blob = new Blob(['stub']);
        (blob as unknown as { __url?: string }).__url = url;
        return blob;
      },
    }));
    vi.stubGlobal('fetch', fetchMock);

    const sampler = createWeatherSampler({
      zoom: 2,
      precipitation: {
        urlTemplate:
          'http://api.test/api/v1/tiles/cldas/2024011500/precipitation/{z}/{x}/{y}.png',
        tileSize: 4,
      },
      temperature: {
        urlTemplate: 'http://api.test/api/v1/tiles/cldas/2024011500/TMP/{z}/{x}/{y}.png',
        tileSize: 4,
      },
    });

    const sample = await sampler.sample({ lon: 0, lat: 0 });

    expect(vi.mocked(fetchMock)).toHaveBeenCalledTimes(2);
    expect(sample.precipitationMm).toBeCloseTo(0, 3);
    expect(sample.temperatureC).toBeCloseTo(0, 3);
    expect(sample.precipitationKind).toBe('none');
  });

  it('rejects when tile fetch fails', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 404,
      blob: async () => new Blob([]),
    }));
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('createImageBitmap', vi.fn(async () => ({ width: 4, height: 4 })));

    const sampler = createWeatherSampler({
      zoom: 2,
      precipitation: {
        urlTemplate:
          'http://api.test/api/v1/tiles/cldas/2024011500/precipitation/{z}/{x}/{y}.png',
        tileSize: 4,
      },
      temperature: {
        urlTemplate: 'http://api.test/api/v1/tiles/cldas/2024011500/TMP/{z}/{x}/{y}.png',
        tileSize: 4,
      },
    });

    await expect(sampler.sample({ lon: 0, lat: 0 })).rejects.toThrow('Failed to load tile');
  });
});

describe('createCloudSampler', () => {
  it('samples cloud cover fraction from tile alpha', async () => {
    const fetchImageData = vi.fn(async () => makeImageData(4, 4, [255, 255, 255, 128]));
    const sampler = createCloudSampler({
      zoom: 2,
      cloud: {
        urlTemplate: 'http://api.test/api/v1/tiles/cldas/2024011500/TCC/{z}/{x}/{y}.png',
        tileSize: 4,
      },
      fetchImageData,
    });

    const sample = await sampler.sample({ lon: 0, lat: 0 });

    expect(sample.cloudCoverFraction).toBeCloseTo(128 / 255, 6);
    expect(fetchImageData).toHaveBeenCalledTimes(1);
  });

  it('returns null for transparent black nodata pixels', async () => {
    const sampler = createCloudSampler({
      zoom: 2,
      cloud: {
        urlTemplate: 'http://api.test/api/v1/tiles/cldas/2024011500/TCC/{z}/{x}/{y}.png',
        tileSize: 4,
      },
      fetchImageData: async () => makeImageData(4, 4, [0, 0, 0, 0]),
    });

    const sample = await sampler.sample({ lon: 0, lat: 0 });
    expect(sample.cloudCoverFraction).toBeNull();
  });

  it('caches the last cloud tile', async () => {
    const fetchImageData = vi.fn(async () => makeImageData(4, 4, [255, 255, 255, 64]));
    const sampler = createCloudSampler({
      zoom: 2,
      cloud: {
        urlTemplate: 'http://api.test/api/v1/tiles/cldas/2024011500/TCC/{z}/{x}/{y}.png',
        tileSize: 4,
      },
      fetchImageData,
    });

    await sampler.sample({ lon: 1, lat: 1 });
    await sampler.sample({ lon: 1, lat: 1 });

    expect(fetchImageData).toHaveBeenCalledTimes(1);
  });
});
