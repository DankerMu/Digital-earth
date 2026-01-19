import { DEFAULT_BASEMAP_ID, isBasemapId, type BasemapId } from '../config/basemaps';
import { useSyncExternalStore } from 'react';

type BasemapState = {
  basemapId: BasemapId;
  setBasemapId: (basemapId: BasemapId) => void;
};

const STORAGE_KEY = 'digital-earth.basemap';

type Listener = () => void;

const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) listener();
}

function safeReadBasemapId(): BasemapId {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_BASEMAP_ID;
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== 'object') return DEFAULT_BASEMAP_ID;
    const record = parsed as Record<string, unknown>;
    const value = record.basemapId;
    if (typeof value !== 'string') return DEFAULT_BASEMAP_ID;
    return isBasemapId(value) ? value : DEFAULT_BASEMAP_ID;
  } catch {
    return DEFAULT_BASEMAP_ID;
  }
}

function safeWriteBasemapId(basemapId: BasemapId) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ basemapId }));
  } catch {
    // ignore write failures (e.g., disabled storage)
  }
}

let basemapId: BasemapId = safeReadBasemapId();

const setBasemapId: BasemapState['setBasemapId'] = (next) => {
  if (Object.is(basemapId, next)) return;
  basemapId = next;
  safeWriteBasemapId(next);
  notify();
};

function getState(): BasemapState {
  return { basemapId, setBasemapId };
}

function setState(partial: Partial<Pick<BasemapState, 'basemapId'>>) {
  if (typeof partial.basemapId === 'string' && isBasemapId(partial.basemapId)) {
    basemapId = partial.basemapId;
    safeWriteBasemapId(partial.basemapId);
    notify();
  }
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

type Selector<T> = (state: BasemapState) => T;

type StoreHook = {
  <T>(selector: Selector<T>): T;
  getState: typeof getState;
  setState: typeof setState;
};

const useBasemapStoreImpl = <T>(selector: Selector<T>): T =>
  useSyncExternalStore(
    subscribe,
    () => selector(getState()),
    () => selector(getState()),
  );

export const useBasemapStore: StoreHook = Object.assign(useBasemapStoreImpl, {
  getState,
  setState,
});

