import { useSyncExternalStore } from 'react';

import type { VoxelCloudQuality } from '../features/voxelCloud/qualityConfig';

export type PerformanceMode = 'low' | 'high';

export interface PerformanceModeState {
  mode: PerformanceMode;
  setMode: (mode: PerformanceMode) => void;
  toggleMode: () => void;
  /**
   * Backwards-compatible alias for code that treated performance mode as a boolean.
   * `enabled=true` maps to `mode='low'`.
   */
  enabled: boolean;
  setEnabled: (enabled: boolean) => void;
  voxelCloudQuality: VoxelCloudQuality;
  setVoxelCloudQuality: (quality: VoxelCloudQuality) => void;
  autoDowngrade: boolean;
  setAutoDowngrade: (enabled: boolean) => void;
}

const STORAGE_KEY = 'digital-earth.performanceMode';

type Listener = () => void;

const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) listener();
}

function normalizePerformanceMode(value: unknown): PerformanceMode {
  return value === 'low' ? 'low' : 'high';
}

function normalizeVoxelCloudQuality(value: unknown): VoxelCloudQuality | null {
  if (value === 'low' || value === 'medium' || value === 'high') return value;
  return null;
}

function safeReadState(): Pick<PerformanceModeState, 'mode' | 'voxelCloudQuality' | 'autoDowngrade'> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { mode: 'high', voxelCloudQuality: 'high', autoDowngrade: true };
    const parsed = JSON.parse(raw) as unknown;
    if (typeof parsed === 'string') {
      const mode = normalizePerformanceMode(parsed);
      return { mode, voxelCloudQuality: mode === 'low' ? 'low' : 'high', autoDowngrade: true };
    }
    if (!parsed || typeof parsed !== 'object') {
      return { mode: 'high', voxelCloudQuality: 'high', autoDowngrade: true };
    }
    const record = parsed as Record<string, unknown>;
    const mode =
      record.mode === 'low' || record.mode === 'high'
        ? record.mode
        : record.enabled === true
          ? 'low'
          : record.enabled === false
            ? 'high'
            : 'high';
    const fallbackQuality = mode === 'low' ? 'low' : 'high';
    const voxelCloudQuality = normalizeVoxelCloudQuality(record.voxelCloudQuality) ?? fallbackQuality;
    const autoDowngrade = typeof record.autoDowngrade === 'boolean' ? record.autoDowngrade : true;
    return { mode, voxelCloudQuality, autoDowngrade };
  } catch {
    return { mode: 'high', voxelCloudQuality: 'high', autoDowngrade: true };
  }
}

function safeWriteState(state: Pick<PerformanceModeState, 'mode' | 'voxelCloudQuality' | 'autoDowngrade'>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // ignore write failures (e.g., disabled storage)
  }
}

const initial = safeReadState();
let mode: PerformanceMode = initial.mode;
let voxelCloudQuality: VoxelCloudQuality = initial.voxelCloudQuality;
let autoDowngrade: boolean = initial.autoDowngrade;

const setMode: PerformanceModeState['setMode'] = (next) => {
  const normalized = normalizePerformanceMode(next);
  if (Object.is(mode, normalized)) return;
  mode = normalized;
  safeWriteState({ mode, voxelCloudQuality, autoDowngrade });
  notify();
};

const setEnabled: PerformanceModeState['setEnabled'] = (enabled) => {
  setMode(enabled ? 'low' : 'high');
};

const toggleMode: PerformanceModeState['toggleMode'] = () => {
  setMode(mode === 'low' ? 'high' : 'low');
};

const setVoxelCloudQuality: PerformanceModeState['setVoxelCloudQuality'] = (quality) => {
  if (voxelCloudQuality === quality) return;
  voxelCloudQuality = quality;
  safeWriteState({ mode, voxelCloudQuality, autoDowngrade });
  notify();
};

const setAutoDowngrade: PerformanceModeState['setAutoDowngrade'] = (enabled) => {
  const normalized = Boolean(enabled);
  if (autoDowngrade === normalized) return;
  autoDowngrade = normalized;
  safeWriteState({ mode, voxelCloudQuality, autoDowngrade });
  notify();
};

function getState(): PerformanceModeState {
  return {
    mode,
    setMode,
    toggleMode,
    enabled: mode === 'low',
    setEnabled,
    voxelCloudQuality,
    setVoxelCloudQuality,
    autoDowngrade,
    setAutoDowngrade,
  };
}

function setState(
  partial: Partial<Pick<PerformanceModeState, 'mode' | 'enabled' | 'voxelCloudQuality' | 'autoDowngrade'>>,
) {
  if (partial.mode === 'low' || partial.mode === 'high') {
    setMode(partial.mode);
  } else if (typeof partial.enabled === 'boolean') {
    setEnabled(partial.enabled);
  }

  if (
    partial.voxelCloudQuality === 'low' ||
    partial.voxelCloudQuality === 'medium' ||
    partial.voxelCloudQuality === 'high'
  ) {
    setVoxelCloudQuality(partial.voxelCloudQuality);
  }

  if (typeof partial.autoDowngrade === 'boolean') {
    setAutoDowngrade(partial.autoDowngrade);
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
