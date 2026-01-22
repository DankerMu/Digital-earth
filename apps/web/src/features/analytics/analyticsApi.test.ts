import { beforeEach, expect, test, vi } from 'vitest';

import {
  clearAnalyticsCache,
  fetchBiasTileSets,
  fetchHistoricalStatistics,
} from './analyticsApi';

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

beforeEach(() => {
  clearAnalyticsCache();
  vi.unstubAllGlobals();
});

test('fetchHistoricalStatistics parses items and caches responses', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    expect(url).toContain('/api/v1/analytics/historical/statistics');
    expect(url).toContain('fmt=png');

    return jsonResponse({
      schema_version: 1,
      generated_at: '2026-01-01T00:00:00Z',
      items: [
        {
          source: ' cldas ',
          variable: 'SNOWFALL',
          window_kind: 'rolling_days',
          window_key: '20260101T000000Z-P7D',
          version: 'v1',
          window_start: '2025-12-25T00:00:00Z',
          window_end: '2026-01-01T00:00:00Z',
          samples: 168,
          dataset_path: 'x.nc',
          metadata_path: 'x.meta.json',
          tiles: {
            mean: {
              template:
                '/api/v1/tiles/statistics/cldas/snowfall/mean/v1/20260101T000000Z-P7D/{z}/{x}/{y}.png',
              legend: '/api/v1/tiles/statistics/cldas/snowfall/legend.json',
            },
          },
        },
      ],
    });
  });

  vi.stubGlobal('fetch', fetchMock);

  const first = await fetchHistoricalStatistics({ apiBaseUrl: 'http://api.test', fmt: 'png' });
  expect(first.items).toHaveLength(1);
  expect(first.items[0]?.source).toBe('cldas');
  expect(first.items[0]?.tiles.mean?.template).toContain('/api/v1/tiles/statistics/');

  const second = await fetchHistoricalStatistics({ apiBaseUrl: 'http://api.test', fmt: 'png' });
  expect(second.items).toHaveLength(1);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test('fetchBiasTileSets parses items and honors the layer filter', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    expect(url).toContain('/api/v1/analytics/bias/tile-sets');
    expect(url).toContain('layer=bias%2Ftemp');

    return jsonResponse({
      schema_version: 1,
      generated_at: '2026-01-01T00:00:00Z',
      items: [
        {
          layer: 'bias/temp',
          time_key: '20260101T000000Z',
          level_key: 'sfc',
          min_zoom: 0,
          max_zoom: 6,
          formats: ['png', 'webp'],
          tile: {
            template: '/api/v1/tiles/bias/temp/20260101T000000Z/sfc/{z}/{x}/{y}.png',
            legend: '/api/v1/tiles/bias/temp/legend.json',
          },
        },
      ],
    });
  });

  vi.stubGlobal('fetch', fetchMock);

  const response = await fetchBiasTileSets({ apiBaseUrl: 'http://api.test', layer: 'bias/temp' });
  expect(response.items).toHaveLength(1);
  expect(response.items[0]?.layer).toBe('bias/temp');
  expect(response.items[0]?.formats).toEqual(['png', 'webp']);
});

