import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createDiagnosticsController } from './diagnosticsController';

describe('diagnosticsController', () => {
  const originalFetch = globalThis.fetch;
  const originalXhr = globalThis.XMLHttpRequest;
  const originalRaf = globalThis.requestAnimationFrame;
  const originalCaf = globalThis.cancelAnimationFrame;

  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    globalThis.XMLHttpRequest = originalXhr;
    globalThis.requestAnimationFrame = originalRaf;
    globalThis.cancelAnimationFrame = originalCaf;
    vi.restoreAllMocks();
  });

  it('toggles enabled state and restores fetch', async () => {
    const rafQueue: FrameRequestCallback[] = [];
    globalThis.requestAnimationFrame = (cb) => {
      rafQueue.push(cb);
      return rafQueue.length;
    };
    globalThis.cancelAnimationFrame = vi.fn();

    const fakeFetch = vi.fn(async () => new Response('ok', { status: 200 }));
    globalThis.fetch = fakeFetch;

    Object.defineProperty(performance, 'memory', {
      value: {
        usedJSHeapSize: 10,
        totalJSHeapSize: 20,
        jsHeapSizeLimit: 30
      },
      configurable: true
    });

    const controller = createDiagnosticsController();
    expect(controller.getSnapshot().enabled).toBe(false);

    controller.setEnabled(true);
    expect(controller.getSnapshot().enabled).toBe(true);
    expect(globalThis.fetch).not.toBe(fakeFetch);

    await globalThis.fetch('https://example.com/tiles/1/2/3.png');
    const afterReq = controller.getSnapshot();
    expect(afterReq.requests.total).toBe(1);
    expect(afterReq.requests.tileTotal).toBe(1);
    expect(afterReq.requestLogs.length).toBe(1);
    expect(afterReq.memory?.usedBytes).toBe(10);

    controller.setEnabled(false);
    expect(controller.getSnapshot().enabled).toBe(false);
    expect(globalThis.fetch).toBe(fakeFetch);
    expect(globalThis.cancelAnimationFrame).toHaveBeenCalled();
  });

  it('captures errors and failed requests', async () => {
    globalThis.requestAnimationFrame = () => 1;
    globalThis.cancelAnimationFrame = vi.fn();

    const fakeFetch = vi.fn(async () => new Response('nope', { status: 500 }));
    globalThis.fetch = fakeFetch;

    const controller = createDiagnosticsController();
    controller.setEnabled(true);

    await globalThis.fetch('/tiles/1/2/3.png');
    const afterFail = controller.getSnapshot();
    expect(afterFail.requests.failed).toBe(1);
    expect(afterFail.requests.tileFailed).toBe(1);

    window.dispatchEvent(
      new ErrorEvent('error', { message: 'boom', error: new Error('boom') })
    );
    const afterError = controller.getSnapshot();
    expect(afterError.errorsTotal).toBe(1);
    expect(afterError.errorLogs.at(-1)?.message).toBe('boom');

    controller.setEnabled(false);
  });
});
