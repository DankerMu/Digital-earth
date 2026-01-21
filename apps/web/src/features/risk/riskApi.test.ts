import { beforeEach, describe, expect, it, vi } from 'vitest';

import { evaluateRisk, getRiskPois } from './riskApi';

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

describe('riskApi', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('fetches risk POIs across dateline split bboxes', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();

      if (url.startsWith('http://api.test/api/v1/risk/pois?')) {
        const parsed = new URL(url);
        const bbox = parsed.searchParams.get('bbox');
        if (bbox === '170,10,180,20') {
          return jsonResponse({
            page: 1,
            page_size: 1000,
            total: 1,
            items: [
              { id: 2, name: 'a', type: 'fire', lon: 179.5, lat: 10.5, alt: null, weight: 1, tags: null, risk_level: null },
            ],
          });
        }
        if (bbox === '-180,10,-170,20') {
          return jsonResponse({
            page: 1,
            page_size: 1000,
            total: 1,
            items: [
              { id: 1, name: 'b', type: 'fire', lon: -179.5, lat: 10.5, alt: null, weight: 1, tags: null, risk_level: null },
            ],
          });
        }
      }

      return new Response('Not Found', { status: 404 });
    });

    vi.stubGlobal('fetch', fetchMock);

    const items = await getRiskPois({
      apiBaseUrl: 'http://api.test/',
      bbox: { min_x: 170, min_y: 10, max_x: -170, max_y: 20 },
    });

    expect(items.map((item) => item.id)).toEqual([1, 2]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('posts to risk evaluate and parses results', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url === 'http://api.test/api/v1/risk/evaluate') {
        expect(init?.method).toBe('POST');
        const body = JSON.parse(String(init?.body ?? '')) as { product_id?: number; valid_time?: string; poi_ids?: number[] };
        expect(body.product_id).toBe(1);
        expect(body.valid_time).toBe('2026-01-01T00:00:00Z');
        expect(body.poi_ids).toEqual([10]);
        return jsonResponse({
          summary: { total: 1, duration_ms: 1, level_counts: { '4': 1 }, reasons: {}, max_level: 4, avg_score: 0.9 },
          results: [{ poi_id: 10, level: 4, score: 0.9, factors: [], reasons: [] }],
        });
      }
      return new Response('Not Found', { status: 404 });
    });

    vi.stubGlobal('fetch', fetchMock);

    const result = await evaluateRisk({
      apiBaseUrl: 'http://api.test/',
      productId: '1',
      validTime: '2026-01-01T00:00:00Z',
      poiIds: [10],
    });

    expect(result.results[0]).toEqual(expect.objectContaining({ poi_id: 10, level: 4 }));
  });

  it('rejects invalid productId values', async () => {
    await expect(
      evaluateRisk({ apiBaseUrl: 'http://api.test/', productId: '  ', validTime: 't' }),
    ).rejects.toThrow(/Invalid productId/);
  });
});

