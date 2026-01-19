import { fetchJson } from './http';
import { beforeEach, expect, test, vi } from 'vitest';

beforeEach(() => {
  vi.unstubAllGlobals();
});

test('parses Retry-After seconds', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('Too Many Requests', { status: 429, headers: { 'retry-after': '120' } }))
  );

  await expect(fetchJson('/x')).rejects.toMatchObject({
    status: 429,
    retryAfterSeconds: 120,
  });
});

test('parses Retry-After http date', async () => {
  const future = new Date(Date.now() + 5_000).toUTCString();
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('Too Many Requests', { status: 429, headers: { 'retry-after': future } }))
  );

  await expect(fetchJson('/x')).rejects.toMatchObject({
    status: 429,
    retryAfterSeconds: expect.any(Number),
  });
});

test('throws network error when fetch rejects', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    })
  );

  await expect(fetchJson('/x')).rejects.toMatchObject({
    message: 'Network Error',
  });
});
