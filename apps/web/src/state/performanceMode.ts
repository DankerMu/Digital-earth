import { useSyncExternalStore } from 'react';

export type PerformanceMode = 'low' | 'high';

type PerformanceModeState = {
  mode: PerformanceMode;
  setMode: (mode: PerformanceMode) => void;
  toggleMode: () => void;
  /**
   * Backwards-compatible alias for code that treated performance mode as a boolean.
   * `enabled=true` maps to `mode='low'`.
   */
  enabled: boolean;
  setEnabled: (enabled: boolean) => void;
};

const STORAGE_KEY = 'digital-earth.performanceMode';

type Listener = () => void;

const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) listener();
}

function normalizePerformanceMode(value: unknown): PerformanceMode {
  return value === 'low' ? 'low' : 'high';
}

function safeReadMode(): PerformanceMode {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return 'high';
    const parsed = JSON.parse(raw) as unknown;
    if (typeof parsed === 'string') return normalizePerformanceMode(parsed);
    if (!parsed || typeof parsed !== 'object') return 'high';
    const record = parsed as Record<string, unknown>;
    if (record.mode === 'low' || record.mode === 'high') return record.mode;
    if (record.enabled === true) return 'low';
    if (record.enabled === false) return 'high';
    return 'high';
  } catch {
    return 'high';
  }
}

function safeWriteMode(mode: PerformanceMode) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ mode }));
  } catch {
    // ignore write failures (e.g., disabled storage)
  }
}

let mode: PerformanceMode = safeReadMode();

const setMode: PerformanceModeState['setMode'] = (next) => {
  const normalized = normalizePerformanceMode(next);
  if (Object.is(mode, normalized)) return;
  mode = normalized;
  safeWriteMode(mode);
  notify();
};

const setEnabled: PerformanceModeState['setEnabled'] = (enabled) => {
  setMode(enabled ? 'low' : 'high');
};

const toggleMode: PerformanceModeState['toggleMode'] = () => {
  setMode(mode === 'low' ? 'high' : 'low');
};

function getState(): PerformanceModeState {
  return { mode, setMode, toggleMode, enabled: mode === 'low', setEnabled };
}

function setState(partial: Partial<Pick<PerformanceModeState, 'mode' | 'enabled'>>) {
  if (partial.mode === 'low' || partial.mode === 'high') {
    setMode(partial.mode);
    return;
  }

  if (typeof partial.enabled === 'boolean') setEnabled(partial.enabled);
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

type Selector<T> = (state: PerformanceModeState) => T;

type StoreHook = {
  <T>(selector: Selector<T>): T;
  getState: typeof getState;
  setState: typeof setState;
};

const usePerformanceModeStoreImpl = <T>(selector: Selector<T>): T =>
  useSyncExternalStore(
    subscribe,
    () => selector(getState()),
    () => selector(getState()),
  );

export const usePerformanceModeStore: StoreHook = Object.assign(
  usePerformanceModeStoreImpl,
  {
    getState,
    setState,
  },
);
