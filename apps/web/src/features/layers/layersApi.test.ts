import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  buildCldasTileUrl,
  buildCldasTileUrlTemplate,
  buildCloudTileUrlTemplate,
  buildEcmwfTemperatureTileUrlTemplate,
  buildPrecipitationTileUrlTemplate,
  clearCldasTileProbeCache,
  probeCldasTileAvailability,
  fetchWindVectorData,
} from './layersApi';

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

describe('layersApi', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
    clearCldasTileProbeCache();
  });

  it('builds a Cesium url template without encoding placeholders', () => {
    const url = buildCldasTileUrlTemplate({
      apiBaseUrl: 'http://api.test/',
      timeKey: '2025-12-22T00:00:00Z',
      variable: 'TMP',
    });

    expect(url).toBe(
      'http://api.test/api/v1/tiles/cldas/2025-12-22T00%3A00%3A00Z/TMP/{z}/{x}/{y}.png',
    );
    expect(url).toContain('{z}');
    expect(url).toContain('{x}');
    expect(url).toContain('{y}');
    expect(url).not.toContain('%7Bz%7D');
  });

  it('builds a concrete CLDAS tile url without placeholders', () => {
    const url = buildCldasTileUrl({
      apiBaseUrl: 'http://api.test/some/prefix/',
      timeKey: '2025-12-22T00:00:00Z',
      variable: 'TMP',
      z: 0,
      x: 0,
      y: 0,
    });

    expect(url).toBe(
      'http://api.test/api/v1/tiles/cldas/2025-12-22T00%3A00%3A00Z/TMP/0/0/0.png',
    );
  });

  it('drops any apiBaseUrl pathname when joining absolute api routes', () => {
    const url = buildCldasTileUrlTemplate({
      apiBaseUrl: 'http://api.test/some/prefix/',
      timeKey: '2024011500',
      variable: 'TMP',
    });

    expect(url).toBe('http://api.test/api/v1/tiles/cldas/2024011500/TMP/{z}/{x}/{y}.png');
    expect(url).not.toContain('/some/prefix/');
  });

  it('falls back to window origin when apiBaseUrl is blank', () => {
    const url = buildCldasTileUrlTemplate({
      apiBaseUrl: '   ',
      timeKey: '2024011500',
      variable: 'TMP',
    });

    expect(url.startsWith(window.location.origin)).toBe(true);
  });

  it('falls back to string trimming when apiBaseUrl cannot be parsed', () => {
    const url = buildCldasTileUrlTemplate({
      apiBaseUrl: 'http://api.test:bad/',
      timeKey: '2024011500',
      variable: 'TMP',
    });

    expect(url).toBe(
      'http://api.test:bad/api/v1/tiles/cldas/2024011500/TMP/{z}/{x}/{y}.png',
    );
  });

  it('builds ECMWF cloud tile templates', () => {
    const url = buildCloudTileUrlTemplate({
      apiBaseUrl: 'http://api.test/',
      timeKey: '2025-12-22T00:00:00Z',
      variable: 'tcc',
    });

    expect(url).toBe(
      'http://api.test/api/v1/tiles/ecmwf/tcc/20251222T000000Z/sfc/{z}/{x}/{y}.png',
    );
    expect(url).toContain('{z}');
    expect(url).toContain('{x}');
    expect(url).toContain('{y}');
  });

  it('defaults ECMWF cloud tiles to surface level', () => {
    const url = buildCloudTileUrlTemplate({
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
    });

    expect(url).toBe(
      'http://api.test/api/v1/tiles/ecmwf/tcc/20240115T000000Z/sfc/{z}/{x}/{y}.png',
    );
  });

  it('builds ECMWF precipitation tile templates', () => {
    const url = buildPrecipitationTileUrlTemplate({
      apiBaseUrl: 'http://api.test/',
      timeKey: '2025-12-22T00:00:00Z',
    });

    expect(url).toBe(
      'http://api.test/api/v1/tiles/ecmwf/precip_amount/20251222T000000Z/sfc/{z}/{x}/{y}.png',
    );
    expect(url).toContain('{z}');
    expect(url).toContain('{x}');
    expect(url).toContain('{y}');
  });

  it('appends a threshold query param when present', () => {
    const url = buildPrecipitationTileUrlTemplate({
      apiBaseUrl: 'http://api.test/',
      timeKey: '2024011500',
      threshold: 2.5,
    });

    expect(url).toBe(
      'http://api.test/api/v1/tiles/ecmwf/precip_amount/20240115T000000Z/sfc/{z}/{x}/{y}.png?threshold=2.5',
    );
  });

  it('omits invalid threshold values', () => {
    const url = buildPrecipitationTileUrlTemplate({
      apiBaseUrl: 'http://api.test/',
      timeKey: '2024011500',
      threshold: Number.NaN,
    });

    expect(url).toBe(
      'http://api.test/api/v1/tiles/ecmwf/precip_amount/20240115T000000Z/sfc/{z}/{x}/{y}.png',
    );
  });

  it('builds ECMWF temperature tile templates with normalized time keys', () => {
    const url = buildEcmwfTemperatureTileUrlTemplate({
      apiBaseUrl: 'http://api.test/',
      timeKey: '2025-12-22T00:00:00Z',
      level: 'sfc',
    });

    expect(url).toBe(
      'http://api.test/api/v1/tiles/ecmwf/temp/20251222T000000Z/sfc/{z}/{x}/{y}.png',
    );
    expect(url).toContain('{z}');
    expect(url).toContain('{x}');
    expect(url).toContain('{y}');
  });

  it('fetches wind vector data using bbox and stride params', async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        u: [1.5, 0],
        v: [-2, 0.1],
        lat: [30, 31],
        lon: [120, 121],
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await fetchWindVectorData({
      apiBaseUrl: 'http://api.test/some/prefix/',
      runTimeKey: '2025-12-22T00:00:00Z',
      timeKey: '2025-12-22T00:00:00Z',
      level: 'sfc',
      bbox: { west: 110, south: 20, east: 130, north: 40 },
      density: 24,
    });

    expect(result.vectors).toHaveLength(2);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://api.test/api/v1/vector/ecmwf/2025-12-22T00%3A00%3A00Z/wind/sfc/2025-12-22T00%3A00%3A00Z?bbox=110,20,130,40&stride=11',
      expect.objectContaining({ signal: undefined }),
    );
  });

  it('filters invalid vector entries and clamps density', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      expect(url).toContain('stride=256');
      return jsonResponse({
        u: [1.5, 'x'],
        v: [-2, 0],
        lat: [30, 1],
        lon: [120, 0],
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await fetchWindVectorData({
      apiBaseUrl: 'http://api.test/',
      runTimeKey: '2025-12-22T00:00:00Z',
      timeKey: '2025-12-22T01:00:00Z',
      level: 'sfc',
      bbox: { west: -10, south: -20, east: 10, north: 20 },
      density: 0,
    });

    expect(result.vectors).toEqual([{ lon: 120, lat: 30, u: 1.5, v: -2 }]);
  });

  it('throws when wind vector fetch returns a non-200 response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('nope', { status: 500 })),
    );

    await expect(
      fetchWindVectorData({
        apiBaseUrl: 'http://api.test',
        runTimeKey: '2025-12-22T00:00:00Z',
        timeKey: '2025-12-22T01:00:00Z',
        level: 'sfc',
        bbox: { west: 0, south: 0, east: 1, north: 1 },
        density: 10,
      }),
    ).rejects.toThrow(/Failed to fetch wind vectors: 500/);
  });

  it('probes tile availability and caches results', async () => {
    const fetchMock = vi.fn(async () => new Response('nope', { status: 404 }));
    vi.stubGlobal('fetch', fetchMock);

    const first = await probeCldasTileAvailability({
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      variable: 'SNOD',
    });
    const second = await probeCldasTileAvailability({
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      variable: 'SNOD',
    });

    expect(first).toEqual({ status: 'missing', httpStatus: 404 });
    expect(second).toEqual({ status: 'missing', httpStatus: 404 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('returns error probe status when fetch throws', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new Error('boom');
    }));

    const result = await probeCldasTileAvailability({
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      variable: 'SNOD',
    });

    expect(result).toEqual({ status: 'error', httpStatus: 0 });
  });

  it('does not cache probe results when requests are aborted', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new DOMException('aborted', 'AbortError'))
      .mockResolvedValueOnce(new Response('nope', { status: 404 }));
    vi.stubGlobal('fetch', fetchMock);

    const controller = new AbortController();
    controller.abort();

    const abortedResult = await probeCldasTileAvailability({
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      variable: 'SNOD',
      signal: controller.signal,
    });

    const retryResult = await probeCldasTileAvailability({
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      variable: 'SNOD',
    });

    expect(abortedResult).toEqual({ status: 'error', httpStatus: 0 });
    expect(retryResult).toEqual({ status: 'missing', httpStatus: 404 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('does not cache AbortError results even without an AbortSignal', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new DOMException('aborted', 'AbortError'))
      .mockResolvedValueOnce(new Response('ok', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    const first = await probeCldasTileAvailability({
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      variable: 'SNOD',
    });
    const second = await probeCldasTileAvailability({
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      variable: 'SNOD',
    });

    expect(first).toEqual({ status: 'error', httpStatus: 0 });
    expect(second).toEqual({ status: 'available', httpStatus: 200 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
