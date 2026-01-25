import { useSyncExternalStore } from 'react';

export type CameraPerspectiveId = 'upward' | 'forward' | 'free';

export const DEFAULT_CAMERA_PERSPECTIVE_ID: CameraPerspectiveId = 'free';

export function isCameraPerspectiveId(value: unknown): value is CameraPerspectiveId {
  return value === 'upward' || value === 'forward' || value === 'free';
}

type CameraPerspectiveState = {
  cameraPerspectiveId: CameraPerspectiveId;
  setCameraPerspectiveId: (cameraPerspectiveId: CameraPerspectiveId) => void;
  cycleCameraPerspective: () => void;
};

const STORAGE_KEY = 'digital-earth.cameraPerspective';

type Listener = () => void;

const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) listener();
}

function safeReadCameraPerspectiveId(): CameraPerspectiveId {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_CAMERA_PERSPECTIVE_ID;
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== 'object') return DEFAULT_CAMERA_PERSPECTIVE_ID;
    const record = parsed as Record<string, unknown>;
    const value = record.cameraPerspectiveId;
    return isCameraPerspectiveId(value) ? value : DEFAULT_CAMERA_PERSPECTIVE_ID;
  } catch {
    return DEFAULT_CAMERA_PERSPECTIVE_ID;
  }
}

function safeWriteCameraPerspectiveId(cameraPerspectiveId: CameraPerspectiveId) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ cameraPerspectiveId }));
  } catch {
    // ignore write failures (e.g., disabled storage)
  }
}

function nextCameraPerspective(current: CameraPerspectiveId): CameraPerspectiveId {
  if (current === 'forward') return 'upward';
  if (current === 'upward') return 'free';
  return 'forward';
}

let cameraPerspectiveId: CameraPerspectiveId = safeReadCameraPerspectiveId();

const setCameraPerspectiveId: CameraPerspectiveState['setCameraPerspectiveId'] = (next) => {
  if (Object.is(cameraPerspectiveId, next)) return;
  cameraPerspectiveId = next;
  safeWriteCameraPerspectiveId(next);
  notify();
};

const cycleCameraPerspective: CameraPerspectiveState['cycleCameraPerspective'] = () => {
  setCameraPerspectiveId(nextCameraPerspective(cameraPerspectiveId));
};

function getState(): CameraPerspectiveState {
  return { cameraPerspectiveId, setCameraPerspectiveId, cycleCameraPerspective };
}

function setState(partial: Partial<Pick<CameraPerspectiveState, 'cameraPerspectiveId'>>) {
  if (isCameraPerspectiveId(partial.cameraPerspectiveId)) {
    cameraPerspectiveId = partial.cameraPerspectiveId;
    safeWriteCameraPerspectiveId(partial.cameraPerspectiveId);
    notify();
  }
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

type Selector<T> = (state: CameraPerspectiveState) => T;

type StoreHook = {
  <T>(selector: Selector<T>): T;
  getState: typeof getState;
  setState: typeof setState;
};

const useCameraPerspectiveStoreImpl = <T>(selector: Selector<T>): T =>
  useSyncExternalStore(
    subscribe,
    () => selector(getState()),
    () => selector(getState()),
  );

export const useCameraPerspectiveStore: StoreHook = Object.assign(useCameraPerspectiveStoreImpl, {
  getState,
  setState,
});

