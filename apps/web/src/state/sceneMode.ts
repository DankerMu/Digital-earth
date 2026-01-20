import { useSyncExternalStore } from 'react';

export type SceneModeId = '3d' | '2d' | 'columbus';

export const DEFAULT_SCENE_MODE_ID: SceneModeId = '3d';

export function isSceneModeId(value: unknown): value is SceneModeId {
  return value === '3d' || value === '2d' || value === 'columbus';
}

type SceneModeState = {
  sceneModeId: SceneModeId;
  setSceneModeId: (sceneModeId: SceneModeId) => void;
};

const STORAGE_KEY = 'digital-earth.sceneMode';

type Listener = () => void;

const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) listener();
}

function safeReadSceneModeId(): SceneModeId {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SCENE_MODE_ID;
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== 'object') return DEFAULT_SCENE_MODE_ID;
    const record = parsed as Record<string, unknown>;
    const value = record.sceneModeId;
    return isSceneModeId(value) ? value : DEFAULT_SCENE_MODE_ID;
  } catch {
    return DEFAULT_SCENE_MODE_ID;
  }
}

function safeWriteSceneModeId(sceneModeId: SceneModeId) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ sceneModeId }));
  } catch {
    // ignore write failures (e.g., disabled storage)
  }
}

let sceneModeId: SceneModeId = safeReadSceneModeId();

const setSceneModeId: SceneModeState['setSceneModeId'] = (next) => {
  if (Object.is(sceneModeId, next)) return;
  sceneModeId = next;
  safeWriteSceneModeId(next);
  notify();
};

function getState(): SceneModeState {
  return { sceneModeId, setSceneModeId };
}

function setState(partial: Partial<Pick<SceneModeState, 'sceneModeId'>>) {
  if (isSceneModeId(partial.sceneModeId)) {
    sceneModeId = partial.sceneModeId;
    safeWriteSceneModeId(partial.sceneModeId);
    notify();
  }
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

type Selector<T> = (state: SceneModeState) => T;

type StoreHook = {
  <T>(selector: Selector<T>): T;
  getState: typeof getState;
  setState: typeof setState;
};

const useSceneModeStoreImpl = <T>(selector: Selector<T>): T =>
  useSyncExternalStore(
    subscribe,
    () => selector(getState()),
    () => selector(getState()),
  );

export const useSceneModeStore: StoreHook = Object.assign(useSceneModeStoreImpl, {
  getState,
  setState,
});

