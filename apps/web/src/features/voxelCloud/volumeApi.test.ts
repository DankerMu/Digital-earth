import { describe, expect, it, vi } from 'vitest';

import { fetchVolumePack } from './volumeApi';

describe('fetchVolumePack', () => {
  it('builds a /api/v1/volume URL with bbox, levels, res, and valid_time', async () => {
    const buffer = new ArrayBuffer(8);
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      arrayBuffer: async () => buffer,
    }));
    vi.stubGlobal('fetch', fetchMock);

    await fetchVolumePack({
      apiBaseUrl: 'http://api.test',
      bbox: { west: 0, south: 1, east: 2, north: 3, bottom: 0, top: 12000 },
      levels: [300.2, 300, 500],
      res: 1000,
      validTime: '2026-01-01T00:00:00Z',
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const firstCall = fetchMock.mock.calls[0] as unknown[];
    const requestUrl = new URL(String(firstCall[0]));
    expect(requestUrl.origin).toBe('http://api.test');
    expect(requestUrl.pathname).toBe('/api/v1/volume');
    expect(requestUrl.searchParams.get('bbox')).toBe('0,1,2,3,0,12000');
    expect(requestUrl.searchParams.get('levels')).toBe('300,500');
    expect(requestUrl.searchParams.get('res')).toBe('1000');
    expect(requestUrl.searchParams.get('valid_time')).toBe('2026-01-01T00:00:00Z');
  });

  it('omits valid_time when it is not provided', async () => {
    const buffer = new ArrayBuffer(8);
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      arrayBuffer: async () => buffer,
    }));
    vi.stubGlobal('fetch', fetchMock);

    await fetchVolumePack({
      apiBaseUrl: 'http://api.test',
      bbox: { west: 0, south: 1, east: 2, north: 3, bottom: 0, top: 12000 },
      levels: [300],
      res: 1000,
    });

    const firstCall = fetchMock.mock.calls[0] as unknown[];
    const requestUrl = new URL(String(firstCall[0]));
    expect(requestUrl.searchParams.get('valid_time')).toBeNull();
  });

  it('throws when the response is not ok', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503 })));

    await expect(
      fetchVolumePack({
        apiBaseUrl: 'http://api.test',
        bbox: { west: 0, south: 0, east: 1, north: 1, bottom: 0, top: 12000 },
        levels: [300],
        res: 1000,
      }),
    ).rejects.toThrow(/Volume API error/i);
  });

  it('throws when levels is not an array', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, arrayBuffer: async () => new ArrayBuffer(0) })));

    await expect(
      fetchVolumePack({
        apiBaseUrl: 'http://api.test',
        bbox: { west: 0, south: 0, east: 1, north: 1, bottom: 0, top: 12000 },
        levels: null as unknown as number[],
        res: 1000,
      }),
    ).rejects.toThrow(/levels must be an array/i);
  });

  it('throws when levels normalize to an empty list', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, arrayBuffer: async () => new ArrayBuffer(0) })));

    await expect(
      fetchVolumePack({
        apiBaseUrl: 'http://api.test',
        bbox: { west: 0, south: 0, east: 1, north: 1, bottom: 0, top: 12000 },
        levels: [Number.NaN, -1, 0],
        res: 1000,
      }),
    ).rejects.toThrow(/at least one valid level/i);
  });
});
