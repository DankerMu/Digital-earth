import { beforeEach, describe, expect, it, vi } from 'vitest';

import { clearAttributionCache, fetchAttribution } from './attributionApi';

const SAMPLE_TEXT = [
  'Attribution (v1.0.0)',
  '',
  'Sources:',
  '- © Cesium — CesiumJS',
  '',
  'Disclaimer:',
  '- demo',
  '',
].join('\n');

describe('fetchAttribution', () => {
  beforeEach(() => {
    clearAttributionCache();
  });

  it('caches ETag and reuses payload on 304', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(SAMPLE_TEXT, {
          status: 200,
          headers: {
            ETag: '"sha256-abc"',
            'X-Attribution-Version': '1.0.0',
          },
        })
      )
      .mockResolvedValueOnce(
        new Response(null, {
          status: 304,
          headers: {
            ETag: '"sha256-abc"',
          },
        })
      );

    vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch);

    const first = await fetchAttribution('http://api.example');
    expect(first.text).toBe(SAMPLE_TEXT);
    expect(first.etag).toBe('"sha256-abc"');

    const second = await fetchAttribution('http://api.example');
    expect(second.text).toBe(SAMPLE_TEXT);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const secondCallOptions = fetchMock.mock.calls[1]?.[1] as RequestInit;
    expect((secondCallOptions.headers as Record<string, string>)['If-None-Match']).toBe(
      '"sha256-abc"'
    );
  });
});
