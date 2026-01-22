import { useSyncExternalStore } from 'react';

export const DEFAULT_TIME_KEY = '2024-01-15T00:00:00Z';

type TimeState = {
  timeKey: string;
  setTimeKey: (timeKey: string) => void;
};

type Listener = () => void;

const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) listener();
}

let timeKey = DEFAULT_TIME_KEY;

function normalizeTimeKey(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

const setTimeKey: TimeState['setTimeKey'] = (next) => {
  const normalized = normalizeTimeKey(next);
  if (!normalized) return;
  if (timeKey === normalized) return;
  timeKey = normalized;
  notify();
};

function getState(): TimeState {
  return { timeKey, setTimeKey };
}

function setState(partial: Partial<Pick<TimeState, 'timeKey'>>) {
  const normalized = normalizeTimeKey(partial.timeKey);
  if (!normalized) return;
  if (timeKey === normalized) return;
  timeKey = normalized;
  notify();
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

type Selector<T> = (state: TimeState) => T;

type StoreHook = {
  <T>(selector: Selector<T>): T;
  getState: typeof getState;
  setState: typeof setState;
};

const useTimeStoreImpl = <T>(selector: Selector<T>): T =>
  useSyncExternalStore(
    subscribe,
    () => selector(getState()),
    () => selector(getState()),
  );

export const useTimeStore: StoreHook = Object.assign(useTimeStoreImpl, {
  getState,
  setState,
});

