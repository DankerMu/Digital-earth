import { useSyncExternalStore } from 'react';

export type EventLayerMode = 'monitoring' | 'history' | 'difference';

export const DEFAULT_EVENT_LAYER_MODE: EventLayerMode = 'monitoring';

export function isEventLayerMode(value: unknown): value is EventLayerMode {
  return value === 'monitoring' || value === 'history' || value === 'difference';
}

type EventLayersState = {
  enabled: boolean;
  mode: EventLayerMode;
  setEnabled: (enabled: boolean) => void;
  setMode: (mode: EventLayerMode) => void;
};

const STORAGE_KEY = 'digital-earth.eventLayers';

type Listener = () => void;

const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) listener();
}

type PersistedState = { enabled?: unknown; mode?: unknown };

function safeReadPersisted(): PersistedState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== 'object') return {};
    return parsed as PersistedState;
  } catch {
    return {};
  }
}

function safeWritePersisted(next: { enabled: boolean; mode: EventLayerMode }) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // ignore write failures (e.g., disabled storage)
  }
}

const persisted = safeReadPersisted();

let enabled = persisted.enabled === true;
let mode: EventLayerMode = isEventLayerMode(persisted.mode)
  ? persisted.mode
  : DEFAULT_EVENT_LAYER_MODE;

const setEnabled: EventLayersState['setEnabled'] = (next) => {
  if (Object.is(enabled, next)) return;
  enabled = next;
  safeWritePersisted({ enabled, mode });
  notify();
};

const setMode: EventLayersState['setMode'] = (next) => {
  if (Object.is(mode, next)) return;
  mode = next;
  safeWritePersisted({ enabled, mode });
  notify();
};

function getState(): EventLayersState {
  return { enabled, mode, setEnabled, setMode };
}

function setState(
  partial: Partial<Pick<EventLayersState, 'enabled' | 'mode'>>,
) {
  let didChange = false;

  if (typeof partial.enabled === 'boolean' && !Object.is(enabled, partial.enabled)) {
    enabled = partial.enabled;
    didChange = true;
  }
  if (isEventLayerMode(partial.mode) && !Object.is(mode, partial.mode)) {
    mode = partial.mode;
    didChange = true;
  }

  if (didChange) {
    safeWritePersisted({ enabled, mode });
    notify();
  }
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

type Selector<T> = (state: EventLayersState) => T;

type StoreHook = {
  <T>(selector: Selector<T>): T;
  getState: typeof getState;
  setState: typeof setState;
};

const useEventLayersStoreImpl = <T>(selector: Selector<T>): T =>
  useSyncExternalStore(
    subscribe,
    () => selector(getState()),
    () => selector(getState()),
  );

export const useEventLayersStore: StoreHook = Object.assign(useEventLayersStoreImpl, {
  getState,
  setState,
});

