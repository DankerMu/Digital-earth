import { useSyncExternalStore } from 'react';

export type ViewerStatsState = {
  fps: number | null;
  setFps: (fps: number | null) => void;
};

type Listener = () => void;

const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) listener();
}

function normalizeFps(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  return value;
}

let fps: number | null = null;

const setFps: ViewerStatsState['setFps'] = (next) => {
  const normalized = normalizeFps(next);
  if (Object.is(fps, normalized)) return;
  fps = normalized;
  notify();
};

function getState(): ViewerStatsState {
  return { fps, setFps };
}

function setState(partial: Partial<Pick<ViewerStatsState, 'fps'>>) {
  if (!('fps' in partial)) return;
  setFps(partial.fps ?? null);
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

type Selector<T> = (state: ViewerStatsState) => T;

type StoreHook = {
  <T>(selector: Selector<T>): T;
  getState: typeof getState;
  setState: typeof setState;
};

const useViewerStatsStoreImpl = <T>(selector: Selector<T>): T =>
  useSyncExternalStore(
    subscribe,
    () => selector(getState()),
    () => selector(getState()),
  );

export const useViewerStatsStore: StoreHook = Object.assign(useViewerStatsStoreImpl, {
  getState,
  setState,
});

