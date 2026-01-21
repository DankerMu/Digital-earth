import { beforeEach, describe, expect, it, vi } from 'vitest';

import { clearProductsCache, getProductDetail, getProductsQuery } from './productsApi';

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

describe('productsApi', () => {
  beforeEach(() => {
    clearProductsCache();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('caches products query and product details by apiBaseUrl', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();

      if (url === 'http://api.test/api/v1/products') {
        return jsonResponse({
          page: 1,
          page_size: 50,
          total: 1,
          items: [
            {
              id: 1,
              title: '降雪',
              hazards: [
                {
                  severity: 'low',
                  geometry: { type: 'Polygon', coordinates: [] },
                  bbox: { min_x: 0, min_y: 0, max_x: 1, max_y: 1 },
                },
              ],
            },
          ],
        });
      }

      if (url === 'http://api.test/api/v1/products/1') {
        return jsonResponse({
          id: 1,
          title: '降雪',
          text: '降雪预警',
          issued_at: '2026-01-01T00:00:00Z',
          valid_from: '2026-01-01T00:00:00Z',
          valid_to: '2026-01-02T00:00:00Z',
          version: 1,
          status: 'published',
          hazards: [
            {
              id: 11,
              severity: 'low',
              geometry: { type: 'Polygon', coordinates: [] },
              bbox: { min_x: 0, min_y: 0, max_x: 1, max_y: 1 },
              valid_from: '2026-01-01T00:00:00Z',
              valid_to: '2026-01-02T00:00:00Z',
            },
          ],
        });
      }

      return new Response('Not Found', { status: 404 });
    });

    vi.stubGlobal('fetch', fetchMock);

    const apiBaseUrl = 'http://api.test/';

    const firstQuery = await getProductsQuery({ apiBaseUrl });
    expect(firstQuery.items).toHaveLength(1);

    const secondQuery = await getProductsQuery({ apiBaseUrl });
    expect(secondQuery.items).toHaveLength(1);

    const firstDetail = await getProductDetail({ apiBaseUrl, productId: '1' });
    expect(firstDetail.title).toBe('降雪');

    const secondDetail = await getProductDetail({ apiBaseUrl, productId: '1' });
    expect(secondDetail.text).toBe('降雪预警');

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('bypasses cached results when cache is set to no-cache', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();

      if (url === 'http://api.test/api/v1/products') {
        return jsonResponse({ page: 1, page_size: 50, total: 0, items: [] });
      }

      if (url === 'http://api.test/api/v1/products/1') {
        return jsonResponse({
          id: 1,
          title: '降雪',
          text: '降雪预警',
          issued_at: '2026-01-01T00:00:00Z',
          valid_from: '2026-01-01T00:00:00Z',
          valid_to: '2026-01-02T00:00:00Z',
          version: 1,
          status: 'published',
          hazards: [],
        });
      }

      return new Response('Not Found', { status: 404 });
    });

    vi.stubGlobal('fetch', fetchMock);

    const apiBaseUrl = 'http://api.test/';

    await getProductsQuery({ apiBaseUrl });
    await getProductsQuery({ apiBaseUrl });
    await getProductsQuery({ apiBaseUrl, cache: 'no-cache' });

    await getProductDetail({ apiBaseUrl, productId: '1' });
    await getProductDetail({ apiBaseUrl, productId: '1' });
    await getProductDetail({ apiBaseUrl, productId: '1', cache: 'no-cache' });

    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it('evicts older cache entries when exceeding the max size', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url.endsWith('/api/v1/products')) {
        return jsonResponse({ page: 1, page_size: 50, total: 0, items: [] });
      }
      return new Response('Not Found', { status: 404 });
    });

    vi.stubGlobal('fetch', fetchMock);

    const baseUrls = Array.from({ length: 11 }, (_, index) => `http://api-${index}.test/`);
    for (const apiBaseUrl of baseUrls) {
      await getProductsQuery({ apiBaseUrl });
    }

    await getProductsQuery({ apiBaseUrl: baseUrls[0]! });

    expect(fetchMock).toHaveBeenCalledTimes(12);
  });
});
