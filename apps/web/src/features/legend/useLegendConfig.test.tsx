import { act, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { clearConfigCache } from '../../config';
import type { LayerType } from './types';
import { useLegendConfig, clearLegendCache } from './useLegendConfig';

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function Harness({ layerType }: { layerType: LayerType | null }) {
  const state = useLegendConfig(layerType);
  return <div data-testid="status">{state.status}</div>;
}

describe('useLegendConfig', () => {
  beforeEach(() => {
    clearConfigCache();
    clearLegendCache();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('debounces legend requests on rapid layer switching', async () => {
    vi.useFakeTimers();

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url === '/config.json') {
        return jsonResponse({ apiBaseUrl: 'http://api.test' });
      }
      if (url === 'http://api.test/api/v1/legends?layer_type=temperature') {
        return jsonResponse({
          colors: ['#0000ff'],
          thresholds: [0],
          labels: ['0'],
        });
      }
      if (url === 'http://api.test/api/v1/legends?layer_type=wind') {
        return jsonResponse({
          colors: ['#00ff00'],
          thresholds: [0],
          labels: ['0'],
        });
      }
      return new Response('Not Found', { status: 404 });
    });

    vi.stubGlobal('fetch', fetchMock);

    const { rerender } = render(<Harness layerType="temperature" />);

    rerender(<Harness layerType="wind" />);

    expect(fetchMock).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });

    const urls = fetchMock.mock.calls.map(([value]) =>
      typeof value === 'string' ? value : value.toString(),
    );

    expect(urls).toContain('/config.json');
    expect(urls).toContain('http://api.test/api/v1/legends?layer_type=wind');
    expect(urls).not.toContain('http://api.test/api/v1/legends?layer_type=temperature');

    vi.useRealTimers();
  });

  it('uses cached legend config without refetching', async () => {
    vi.useFakeTimers();

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url === '/config.json') {
        return jsonResponse({ apiBaseUrl: 'http://api.test' });
      }
      if (url === 'http://api.test/api/v1/legends?layer_type=temperature') {
        return jsonResponse({
          colors: ['#0000ff'],
          thresholds: [0],
          labels: ['0'],
        });
      }
      return new Response('Not Found', { status: 404 });
    });

    vi.stubGlobal('fetch', fetchMock);

    const { unmount } = render(<Harness layerType="temperature" />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });

    await act(async () => {
      await Promise.resolve();
    });

    const temperatureLegendUrl = 'http://api.test/api/v1/legends?layer_type=temperature';
    const urlsAfterFirstLoad = fetchMock.mock.calls.map(([value]) =>
      typeof value === 'string' ? value : value.toString(),
    );
    expect(urlsAfterFirstLoad).toContain(temperatureLegendUrl);

    unmount();

    render(<Harness layerType="temperature" />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });

    const urlsAfterSecondLoad = fetchMock.mock.calls.map(([value]) =>
      typeof value === 'string' ? value : value.toString(),
    );

    const temperatureLegendCalls = urlsAfterSecondLoad.filter(
      (url) => url === temperatureLegendUrl,
    );
    expect(temperatureLegendCalls).toHaveLength(1);

    vi.useRealTimers();
  });

  it('aborts an in-flight request when switching layers', async () => {
    vi.useFakeTimers();

    const temperatureDeferred = createDeferred<Response>();
    let temperatureSignal: AbortSignal | undefined;

    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === 'string' ? input : input.toString();
        if (url === '/config.json') {
          return jsonResponse({ apiBaseUrl: 'http://api.test' });
        }

        if (url === 'http://api.test/api/v1/legends?layer_type=temperature') {
          const signal = init?.signal as AbortSignal | undefined;
          if (signal) {
            temperatureSignal = signal;
            signal.addEventListener('abort', () => {
              temperatureDeferred.reject(new DOMException('Aborted', 'AbortError'));
            });
          }
          return temperatureDeferred.promise;
        }

        if (url === 'http://api.test/api/v1/legends?layer_type=wind') {
          return jsonResponse({
            colors: ['#00ff00'],
            thresholds: [0],
            labels: ['0'],
          });
        }

        return new Response('Not Found', { status: 404 });
      },
    );

    vi.stubGlobal('fetch', fetchMock);

    const { rerender } = render(<Harness layerType="temperature" />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });

    expect(fetchMock).toHaveBeenCalledWith(
      'http://api.test/api/v1/legends?layer_type=temperature',
      expect.any(Object),
    );
    if (!temperatureSignal) {
      throw new Error('Expected legend request to include an AbortSignal');
    }
    expect(temperatureSignal.aborted).toBe(false);

    rerender(<Harness layerType="wind" />);

    expect(temperatureSignal.aborted).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });

    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByTestId('status')).toHaveTextContent('loaded');

    vi.useRealTimers();
  });
});
