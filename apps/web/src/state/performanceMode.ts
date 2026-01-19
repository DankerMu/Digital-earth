import { useSyncExternalStore } from 'react';

type PerformanceModeState = {
  enabled: boolean;
  setEnabled: (enabled: boolean) => void;
};

const STORAGE_KEY = 'digital-earth.performanceMode';

type Listener = () => void;

const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) listener();
}

function safeReadEnabled(): boolean {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return false;
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== 'object') return false;
    const record = parsed as Record<string, unknown>;
    return record.enabled === true;
  } catch {
    return false;
  }
}

function safeWriteEnabled(enabled: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ enabled }));
  } catch {
    // ignore write failures (e.g., disabled storage)
  }
}

let enabled = safeReadEnabled();

const setEnabled: PerformanceModeState['setEnabled'] = (next) => {
  if (Object.is(enabled, next)) return;
  enabled = next;
  safeWriteEnabled(next);
  notify();
};

function getState(): PerformanceModeState {
  return { enabled, setEnabled };
}

function setState(partial: Partial<Pick<PerformanceModeState, 'enabled'>>) {
  if (typeof partial.enabled === 'boolean') {
    enabled = partial.enabled;
    safeWriteEnabled(partial.enabled);
    notify();
  }
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
