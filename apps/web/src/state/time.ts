import { useSyncExternalStore } from 'react';

export const DEFAULT_RUN_TIME_KEY = '2025-12-22T00:00:00Z';
export const DEFAULT_LEVEL_KEY = 'sfc';

function toUtcIsoNoMillis(date: Date): string {
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

function addHoursUtcIso(baseUtcIso: string, hours: number): string {
  const base = new Date(baseUtcIso);
  if (Number.isNaN(base.getTime())) return baseUtcIso;
  return toUtcIsoNoMillis(new Date(base.getTime() + hours * 60 * 60 * 1000));
}

export const DEFAULT_VALID_TIME_KEY = addHoursUtcIso(DEFAULT_RUN_TIME_KEY, 3);

// Backwards-compatible alias: historically `timeKey` was the only concept of time.
// It now maps to ECMWF valid time by default.
export const DEFAULT_TIME_KEY = DEFAULT_VALID_TIME_KEY;

type TimeState = {
  runTimeKey: string;
  validTimeKey: string;
  levelKey: string;
  // Backwards-compatible alias for `validTimeKey`.
  timeKey: string;
  setRunTimeKey: (runTimeKey: string) => void;
  setValidTimeKey: (validTimeKey: string) => void;
  setLevelKey: (levelKey: string) => void;
  // Backwards-compatible alias for `setValidTimeKey`.
  setTimeKey: (timeKey: string) => void;
};

type Listener = () => void;

const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) listener();
}

let runTimeKey = DEFAULT_RUN_TIME_KEY;
let validTimeKey = DEFAULT_VALID_TIME_KEY;
let levelKey = DEFAULT_LEVEL_KEY;

function normalizeTimeKey(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim().replace(/\.\d{3}Z$/, 'Z');
  return trimmed.length > 0 ? trimmed : null;
}

function normalizeLevelKey(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

const setRunTimeKey: TimeState['setRunTimeKey'] = (next) => {
  const normalized = normalizeTimeKey(next);
  if (!normalized) return;
  if (runTimeKey === normalized) return;
  runTimeKey = normalized;
  notify();
};

const setValidTimeKey: TimeState['setValidTimeKey'] = (next) => {
  const normalized = normalizeTimeKey(next);
  if (!normalized) return;
  if (validTimeKey === normalized) return;
  validTimeKey = normalized;
  notify();
};

const setLevelKey: TimeState['setLevelKey'] = (next) => {
  const normalized = normalizeLevelKey(next);
  if (!normalized) return;
  if (levelKey === normalized) return;
  levelKey = normalized;
  notify();
};

const setTimeKey: TimeState['setTimeKey'] = (next) => {
  setValidTimeKey(next);
};

function getState(): TimeState {
  return {
    runTimeKey,
    validTimeKey,
    levelKey,
    timeKey: validTimeKey,
    setRunTimeKey,
    setValidTimeKey,
    setLevelKey,
    setTimeKey,
  };
}

function setState(
  partial: Partial<Pick<TimeState, 'runTimeKey' | 'validTimeKey' | 'levelKey' | 'timeKey'>>,
) {
  const nextRun = normalizeTimeKey(partial.runTimeKey);
  const nextValid = normalizeTimeKey(partial.validTimeKey ?? partial.timeKey);
  const nextLevel = normalizeLevelKey(partial.levelKey);

  let changed = false;
  if (nextRun && runTimeKey !== nextRun) {
    runTimeKey = nextRun;
    changed = true;
  }
  if (nextValid && validTimeKey !== nextValid) {
    validTimeKey = nextValid;
    changed = true;
  }
  if (nextLevel && levelKey !== nextLevel) {
    levelKey = nextLevel;
    changed = true;
  }

  if (changed) notify();
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
