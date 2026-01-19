import { describe, expect, it, vi } from 'vitest';

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('loadConfig', () => {
  it('caches the first /config.json response', async () => {
    vi.resetModules();

    const fetchMock = vi.fn(async () => jsonResponse({ apiBaseUrl: 'http://api.test' }));
    vi.stubGlobal('fetch', fetchMock);

    const { loadConfig } = await import('./config');

    const first = await loadConfig();
    const second = await loadConfig();

    expect(first).toEqual({ apiBaseUrl: 'http://api.test' });
    expect(second).toEqual({ apiBaseUrl: 'http://api.test' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('throws when /config.json fails', async () => {
    vi.resetModules();
    vi.stubGlobal('fetch', vi.fn(async () => new Response('nope', { status: 500 })));

    const { loadConfig } = await import('./config');

    await expect(loadConfig()).rejects.toThrow('Failed to load /config.json: 500');
  });
});

