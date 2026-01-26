import { useSyncExternalStore } from 'react';

type RealLightingState = {
  enabled: boolean;
  setEnabled: (enabled: boolean) => void;
  toggleEnabled: () => void;
};

const STORAGE_KEY = 'digital-earth.realLighting';

type Listener = () => void;

const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) listener();
}

function safeReadEnabled(): boolean {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return true;
    const parsed = JSON.parse(raw) as unknown;
    if (typeof parsed === 'boolean') return parsed;
    if (!parsed || typeof parsed !== 'object') return true;
    const record = parsed as Record<string, unknown>;
    return typeof record.enabled === 'boolean' ? record.enabled : true;
  } catch {
    return true;
  }
}

function safeWriteEnabled(nextEnabled: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ enabled: nextEnabled }));
  } catch {
    // ignore write failures (e.g., disabled storage)
  }
}

let enabled = safeReadEnabled();

const setEnabled: RealLightingState['setEnabled'] = (next) => {
  if (Object.is(enabled, next)) return;
  enabled = next;
  safeWriteEnabled(next);
  notify();
};

const toggleEnabled: RealLightingState['toggleEnabled'] = () => {
  setEnabled(!enabled);
};

function getState(): RealLightingState {
  return { enabled, setEnabled, toggleEnabled };
}

function setState(partial: Partial<Pick<RealLightingState, 'enabled'>>) {
  if (typeof partial.enabled !== 'boolean') return;
  enabled = partial.enabled;
  safeWriteEnabled(partial.enabled);
  notify();
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

type Selector<T> = (state: RealLightingState) => T;

type StoreHook = {
  <T>(selector: Selector<T>): T;
  getState: typeof getState;
  setState: typeof setState;
};

const useRealLightingStoreImpl = <T>(selector: Selector<T>): T =>
  useSyncExternalStore(
    subscribe,
    () => selector(getState()),
    () => selector(getState()),
  );

export const useRealLightingStore: StoreHook = Object.assign(useRealLightingStoreImpl, {
  getState,
  setState,
});

