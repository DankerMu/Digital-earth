import { clearConfigCache, loadConfig } from './config';
import { beforeEach, expect, test, vi } from 'vitest';

beforeEach(() => {
  clearConfigCache();
  vi.unstubAllGlobals();
});

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

test('caches the first /config.json response', async () => {
  const fetchMock = vi.fn(async () => jsonResponse({ apiBaseUrl: 'http://api.test' }));
  vi.stubGlobal('fetch', fetchMock);

  const first = await loadConfig();
  const second = await loadConfig();

  expect(first).toEqual({ apiBaseUrl: 'http://api.test' });
  expect(second).toEqual({ apiBaseUrl: 'http://api.test' });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock).toHaveBeenCalledWith('/config.json', { cache: 'no-store' });
});

test('throws when /config.json is missing apiBaseUrl', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({})));

  await expect(loadConfig()).rejects.toThrow('Invalid /config.json: apiBaseUrl');
});

test('throws when /config.json is not an object', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse('nope')));

  await expect(loadConfig()).rejects.toThrow('Invalid /config.json');
});

test('bubbles up http errors from /config.json', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('nope', { status: 500 })));

  await expect(loadConfig()).rejects.toMatchObject({ status: 500 });
});
