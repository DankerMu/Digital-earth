import type {
  DiagnosticsErrorLogEntry,
  DiagnosticsRequestLogEntry,
  DiagnosticsSnapshot
} from './types';
import { isTileUrl } from './isTileUrl';

const STORAGE_KEY = 'de:diagnostics:enabled';
const MAX_LOG_ENTRIES = 200;

type PerformanceMemoryLike = {
  usedJSHeapSize: number;
  totalJSHeapSize: number;
  jsHeapSizeLimit: number;
};

type XhrWithDiagnostics = XMLHttpRequest & {
  __deDiag?: { method: string; url: string; isTile: boolean; startedAt: number };
};

export type DiagnosticsController = {
  start: () => void;
  stop: () => void;
  setEnabled: (enabled: boolean) => void;
  getSnapshot: () => DiagnosticsSnapshot;
  subscribe: (listener: () => void) => () => void;
  exportToJson: () => string;
};

export function createDiagnosticsController(): DiagnosticsController {
  const listeners = new Set<() => void>();

  const requestLogs: DiagnosticsRequestLogEntry[] = [];
  const errorLogs: DiagnosticsErrorLogEntry[] = [];

  let enabled = readEnabledFromStorage();
  let started = false;
  let rafId: number | null = null;
  let memoryIntervalId: number | null = null;

  let originalFetch: typeof fetch | null = null;
  let originalXhrOpen: typeof XMLHttpRequest.prototype.open | null = null;
  let originalXhrSend: typeof XMLHttpRequest.prototype.send | null = null;
  let perfObserver: PerformanceObserver | null = null;

  let fpsFrames = 0;
  let fpsLastTime = 0;

  let snapshot: DiagnosticsSnapshot = buildSnapshot({
    enabled,
    fps: undefined,
    memory: undefined,
    requests: {
      total: 0,
      tileTotal: 0,
      failed: 0,
      tileFailed: 0,
      cacheHits: 0,
      tileCacheHits: 0
    },
    errorsTotal: 0,
    requestLogs,
    errorLogs
  });

  function notify() {
    for (const listener of listeners) listener();
  }

  function setSnapshot(
    updater: (prev: DiagnosticsSnapshot) => DiagnosticsSnapshot
  ) {
    snapshot = updater(snapshot);
    notify();
  }

  function subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  function getSnapshot() {
    return snapshot;
  }

  function setEnabled(nextEnabled: boolean) {
    enabled = nextEnabled;
    try {
      localStorage.setItem(STORAGE_KEY, enabled ? '1' : '0');
    } catch {
      // ignore
    }
    setSnapshot((prev) => buildSnapshot({ ...prev, enabled }));

    if (enabled) start();
    else stop();
  }

  function start() {
    if (started) return;
    started = true;

    startFps();
    startMemory();
    startErrors();
    startRequestTracking();
  }

  function stop() {
    if (!started) return;
    started = false;

    stopFps();
    stopMemory();
    stopErrors();
    stopRequestTracking();
  }

  function exportToJson() {
    const data = {
      exportedAt: new Date().toISOString(),
      snapshot
    };
    return JSON.stringify(data, null, 2);
  }

  function startFps() {
    fpsFrames = 0;
    fpsLastTime = performance.now();

    const tick = (now: number) => {
      fpsFrames += 1;
      const delta = now - fpsLastTime;
      if (delta >= 1000) {
        const fps = Math.round((fpsFrames * 1000) / delta);
        fpsFrames = 0;
        fpsLastTime = now;
        setSnapshot((prev) => buildSnapshot({ ...prev, fps }));
      }
      rafId = requestAnimationFrame(tick);
    };

    rafId = requestAnimationFrame(tick);
  }

  function stopFps() {
    if (rafId != null) cancelAnimationFrame(rafId);
    rafId = null;
  }

  function startMemory() {
    const readMemory = () => {
      const mem = (performance as unknown as { memory?: PerformanceMemoryLike })
        .memory;
      if (!mem) return;
      setSnapshot((prev) =>
        buildSnapshot({
          ...prev,
          memory: {
            usedBytes: mem.usedJSHeapSize,
            totalBytes: mem.totalJSHeapSize,
            limitBytes: mem.jsHeapSizeLimit
          }
        })
      );
    };

    readMemory();
    memoryIntervalId = window.setInterval(readMemory, 2000);
  }

  function stopMemory() {
    if (memoryIntervalId != null) window.clearInterval(memoryIntervalId);
    memoryIntervalId = null;
  }

  function onErrorEvent(event: ErrorEvent) {
    const message = event.error instanceof Error ? event.error.message : event.message;
    const stack = event.error instanceof Error ? event.error.stack : undefined;
    pushError({ at: Date.now(), message, stack });
  }

  function onUnhandledRejection(event: PromiseRejectionEvent) {
    const reason = event.reason;
    if (reason instanceof Error) {
      pushError({ at: Date.now(), message: reason.message, stack: reason.stack });
      return;
    }
    pushError({ at: Date.now(), message: String(reason) });
  }

  function startErrors() {
    window.addEventListener('error', onErrorEvent);
    window.addEventListener('unhandledrejection', onUnhandledRejection);
  }

  function stopErrors() {
    window.removeEventListener('error', onErrorEvent);
    window.removeEventListener('unhandledrejection', onUnhandledRejection);
  }

  function pushError(entry: DiagnosticsErrorLogEntry) {
    errorLogs.push(entry);
    trimLogs(errorLogs);
    setSnapshot((prev) =>
      buildSnapshot({
        ...prev,
        errorsTotal: prev.errorsTotal + 1
      })
    );
  }

  function pushRequest(entry: DiagnosticsRequestLogEntry) {
    requestLogs.push(entry);
    trimLogs(requestLogs);
  }

  function bumpRequestCounts(opts: { isTile: boolean; ok: boolean }) {
    setSnapshot((prev) => {
      const next = { ...prev.requests };
      next.total += 1;
      if (opts.isTile) next.tileTotal += 1;
      if (!opts.ok) {
        next.failed += 1;
        if (opts.isTile) next.tileFailed += 1;
      }
      return buildSnapshot({ ...prev, requests: next });
    });
  }

  function bumpCacheHit(url: string) {
    const isTile = isTileUrl(url);
    setSnapshot((prev) => {
      const next = { ...prev.requests };
      next.cacheHits += 1;
      if (isTile) next.tileCacheHits += 1;
      return buildSnapshot({ ...prev, requests: next });
    });
  }

  function startRequestTracking() {
    if (originalFetch || originalXhrOpen || originalXhrSend) return;

    originalFetch = globalThis.fetch;
    globalThis.fetch = async (input, init) => {
      const startedAt = performance.now();
      const url = extractRequestUrl(input);
      const method = extractRequestMethod(input, init);
      const isTile = isTileUrl(url);

      try {
        const response = await originalFetch!(input, init);
        const durationMs = performance.now() - startedAt;
        const ok = response.ok;
        pushRequest({
          at: Date.now(),
          url,
          method,
          ok,
          status: response.status,
          durationMs,
          isTile
        });
        bumpRequestCounts({ isTile, ok });
        return response;
      } catch (err) {
        const durationMs = performance.now() - startedAt;
        pushRequest({
          at: Date.now(),
          url,
          method,
          ok: false,
          durationMs,
          isTile
        });
        bumpRequestCounts({ isTile, ok: false });
        throw err;
      }
    };

    originalXhrOpen = XMLHttpRequest.prototype.open;
    originalXhrSend = XMLHttpRequest.prototype.send;

    XMLHttpRequest.prototype.open = function (
      method: string,
      url: string,
      async?: boolean,
      user?: string | null,
      password?: string | null
    ) {
      const xhr = this as XhrWithDiagnostics;
      xhr.__deDiag = {
        method: method.toUpperCase(),
        url: String(url),
        isTile: isTileUrl(String(url)),
        startedAt: 0
      };
      return originalXhrOpen!.call(this, method, url, async ?? true, user, password);
    };

    XMLHttpRequest.prototype.send = function (
      body?: Document | XMLHttpRequestBodyInit | null
    ) {
      const xhr = this as XhrWithDiagnostics;
      const meta = xhr.__deDiag;
      if (meta) {
        meta.startedAt = performance.now();
      }

      const onLoadEnd = () => {
        const now = performance.now();
        const ok = this.status >= 200 && this.status < 400;
        const durationMs = meta ? now - meta.startedAt : 0;
        pushRequest({
          at: Date.now(),
          url: meta?.url ?? 'unknown',
          method: meta?.method ?? 'GET',
          ok,
          status: this.status,
          durationMs,
          isTile: meta?.isTile ?? false
        });
        bumpRequestCounts({ isTile: meta?.isTile ?? false, ok });
      };

      this.addEventListener('loadend', onLoadEnd, { once: true });
      return originalXhrSend!.call(this, body ?? null);
    };

    if ('PerformanceObserver' in globalThis) {
      try {
        perfObserver = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            if (entry.entryType !== 'resource') continue;
            const resource = entry as PerformanceResourceTiming;
            if (!isTileUrl(resource.name)) continue;
            const isHit =
              resource.transferSize === 0 &&
              (resource.encodedBodySize > 0 || resource.decodedBodySize > 0);
            if (isHit) bumpCacheHit(resource.name);
          }
        });
        perfObserver.observe({ type: 'resource', buffered: true });
      } catch {
        perfObserver = null;
      }
    }
  }

  function stopRequestTracking() {
    if (originalFetch) globalThis.fetch = originalFetch;
    originalFetch = null;

    if (originalXhrOpen) XMLHttpRequest.prototype.open = originalXhrOpen;
    if (originalXhrSend) XMLHttpRequest.prototype.send = originalXhrSend;
    originalXhrOpen = null;
    originalXhrSend = null;

    if (perfObserver) perfObserver.disconnect();
    perfObserver = null;
  }

  return {
    start,
    stop,
    setEnabled,
    getSnapshot,
    subscribe,
    exportToJson
  };
}

function readEnabledFromStorage(): boolean {
  let enabledFromStorage = false;
  try {
    enabledFromStorage = localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    enabledFromStorage = false;
  }

  if (enabledFromStorage) return true;

  try {
    const search = globalThis.location?.search;
    if (!search) return false;
    const params = new URLSearchParams(search);
    const value = params.get('diagnostics') ?? params.get('diag');
    return value === '1' || value === 'true';
  } catch {
    return false;
  }
}

function buildSnapshot(snapshot: DiagnosticsSnapshot): DiagnosticsSnapshot {
  return {
    ...snapshot,
    requests: { ...snapshot.requests },
    requestLogs: snapshot.requestLogs,
    errorLogs: snapshot.errorLogs
  };
}

function trimLogs<T>(logs: T[]) {
  if (logs.length <= MAX_LOG_ENTRIES) return;
  logs.splice(0, logs.length - MAX_LOG_ENTRIES);
}

function extractRequestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

function extractRequestMethod(
  input: RequestInfo | URL,
  init?: RequestInit
): string {
  if (init?.method) return init.method.toUpperCase();
  if (input instanceof Request) return input.method.toUpperCase();
  return 'GET';
}
