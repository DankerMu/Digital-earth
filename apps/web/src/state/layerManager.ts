import { useSyncExternalStore } from 'react';

export type LayerType = 'temperature' | 'cloud' | 'precipitation' | 'wind' | 'snow-depth';

export type LayerConfig = {
  id: string;
  type: LayerType;
  variable: string;
  level?: number;
  threshold?: number;
  opacity: number;
  visible: boolean;
  zIndex: number;
};

export type LayerUpdate = Partial<
  Pick<
    LayerConfig,
    'type' | 'variable' | 'level' | 'threshold' | 'opacity' | 'visible' | 'zIndex'
  >
>;

type LayerManagerState = {
  layers: LayerConfig[];
  registerLayer: (config: LayerConfig) => void;
  unregisterLayer: (id: string) => void;
  updateLayer: (id: string, partial: LayerUpdate) => void;
  setLayerOpacity: (id: string, opacity: number) => void;
  setLayerVisible: (id: string, visible: boolean) => void;
  getLayersByType: (type: LayerType) => LayerConfig[];
  getVisibleLayers: () => LayerConfig[];
  batch: <T>(fn: () => T) => T;
};

const STORAGE_KEY = 'digital-earth.layers';

type Listener = () => void;

const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) listener();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function isLayerType(value: unknown): value is LayerType {
  return (
    value === 'temperature' ||
    value === 'cloud' ||
    value === 'precipitation' ||
    value === 'wind' ||
    value === 'snow-depth'
  );
}

function clampOpacity(value: unknown): number {
  if (!isFiniteNumber(value)) return 1;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

function sanitizeLayerConfig(value: unknown): LayerConfig | null {
  if (!isRecord(value)) return null;
  const id = value.id;
  const type = value.type;
  const variable = value.variable;

  if (!isNonEmptyString(id) || !isLayerType(type) || !isNonEmptyString(variable)) {
    return null;
  }

  const levelRaw = value.level;
  const level = isFiniteNumber(levelRaw) ? levelRaw : undefined;
  const thresholdRaw = value.threshold;
  const threshold = isFiniteNumber(thresholdRaw) ? thresholdRaw : undefined;
  const opacity = clampOpacity(value.opacity);
  const visible = value.visible === true;
  const zIndex = isFiniteNumber(value.zIndex) ? value.zIndex : 0;

  return {
    id: id.trim(),
    type,
    variable: variable.trim(),
    ...(level == null ? {} : { level }),
    ...(threshold == null ? {} : { threshold }),
    opacity,
    visible,
    zIndex,
  };
}

function layerConfigsEqual(a: LayerConfig, b: LayerConfig): boolean {
  return (
    a.id === b.id &&
    a.type === b.type &&
    a.variable === b.variable &&
    Object.is(a.level, b.level) &&
    Object.is(a.threshold, b.threshold) &&
    Object.is(a.opacity, b.opacity) &&
    a.visible === b.visible &&
    Object.is(a.zIndex, b.zIndex)
  );
}

function sortLayers(next: LayerConfig[]): LayerConfig[] {
  return [...next].sort(
    (a, b) => a.zIndex - b.zIndex || a.id.localeCompare(b.id),
  );
}

function enforceExclusivityOnLoad(next: LayerConfig[]): LayerConfig[] {
  const sorted = sortLayers(next);
  const nextById = new Map<string, LayerConfig>();
  for (const layer of sorted) {
    nextById.set(layer.id, layer);
  }

  const hasVisibleType = new Set<LayerType>();

  for (let i = sorted.length - 1; i >= 0; i -= 1) {
    const layer = sorted[i]!;
    if (!layer.visible) continue;
    if (!hasVisibleType.has(layer.type)) {
      hasVisibleType.add(layer.type);
      continue;
    }

    const hidden = { ...layer, visible: false };
    nextById.set(hidden.id, hidden);
  }

  return sortLayers(Array.from(nextById.values()));
}

function safeReadLayers(): LayerConfig[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];

    const parsed = JSON.parse(raw) as unknown;
    const rawLayers: unknown =
      Array.isArray(parsed) ? parsed : isRecord(parsed) ? parsed.layers : null;

    if (!Array.isArray(rawLayers)) return [];

    const byId = new Map<string, LayerConfig>();
    for (const item of rawLayers) {
      const sanitized = sanitizeLayerConfig(item);
      if (!sanitized) continue;
      byId.set(sanitized.id, sanitized);
    }

    return enforceExclusivityOnLoad(Array.from(byId.values()));
  } catch {
    return [];
  }
}

function safeWriteLayers(next: LayerConfig[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ layers: next }));
  } catch {
    // ignore write failures (e.g., disabled storage)
  }
}

let layers: LayerConfig[] = safeReadLayers();

let batchDepth = 0;
let needsNotify = false;
let needsPersist = false;

function flushIfNeeded() {
  if (batchDepth > 0) return;
  if (needsPersist) {
    needsPersist = false;
    safeWriteLayers(layers);
  }
  if (needsNotify) {
    needsNotify = false;
    notify();
  }
}

function markChanged() {
  needsPersist = true;
  needsNotify = true;
  flushIfNeeded();
}

const batch: LayerManagerState['batch'] = (fn) => {
  batchDepth += 1;
  try {
    return fn();
  } finally {
    batchDepth -= 1;
    flushIfNeeded();
  }
};

function replaceLayers(next: LayerConfig[]) {
  if (next === layers) return;
  layers = next;
  markChanged();
}

function applyExclusiveVisibility(
  next: LayerConfig[],
  type: LayerType,
  visibleLayerId: string,
): LayerConfig[] {
  let didChange = false;
  const updated = next.map((layer) => {
    if (layer.type !== type) return layer;
    const shouldBeVisible = layer.id === visibleLayerId;
    if (layer.visible === shouldBeVisible) return layer;
    didChange = true;
    return { ...layer, visible: shouldBeVisible };
  });
  return didChange ? updated : next;
}

const registerLayer: LayerManagerState['registerLayer'] = (config) => {
  const sanitized = sanitizeLayerConfig(config);
  if (!sanitized) return;

  const existing = layers.find((layer) => layer.id === sanitized.id);
  let nextLayers: LayerConfig[];

  if (existing && layerConfigsEqual(existing, sanitized)) {
    return;
  }

  if (existing) {
    nextLayers = layers.map((layer) => (layer.id === sanitized.id ? sanitized : layer));
  } else {
    nextLayers = [...layers, sanitized];
  }

  if (sanitized.visible) {
    nextLayers = applyExclusiveVisibility(nextLayers, sanitized.type, sanitized.id);
  }

  replaceLayers(sortLayers(nextLayers));
};

const unregisterLayer: LayerManagerState['unregisterLayer'] = (id) => {
  if (!isNonEmptyString(id)) return;
  const trimmed = id.trim();
  if (!layers.some((layer) => layer.id === trimmed)) return;
  replaceLayers(layers.filter((layer) => layer.id !== trimmed));
};

const updateLayer: LayerManagerState['updateLayer'] = (id, partial) => {
  if (!isNonEmptyString(id)) return;
  const trimmedId = id.trim();
  const existing = layers.find((layer) => layer.id === trimmedId);
  if (!existing) return;

  let next: LayerConfig = existing;
  let didChange = false;

  if (partial.type && isLayerType(partial.type) && partial.type !== next.type) {
    next = { ...next, type: partial.type };
    didChange = true;
  }

  if (typeof partial.variable === 'string') {
    const trimmedVar = partial.variable.trim();
    if (trimmedVar.length > 0 && trimmedVar !== next.variable) {
      next = { ...next, variable: trimmedVar };
      didChange = true;
    }
  }

  if ('level' in partial) {
    const nextLevel = isFiniteNumber(partial.level) ? partial.level : undefined;
    if (!Object.is(next.level, nextLevel)) {
      if (nextLevel == null) {
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { level: _level, ...rest } = next;
        next = rest;
      } else {
        next = { ...next, level: nextLevel };
      }
      didChange = true;
    }
  }

  if ('threshold' in partial) {
    const nextThreshold = isFiniteNumber(partial.threshold) ? partial.threshold : undefined;
    if (!Object.is(next.threshold, nextThreshold)) {
      if (nextThreshold == null) {
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { threshold: _threshold, ...rest } = next;
        next = rest;
      } else {
        next = { ...next, threshold: nextThreshold };
      }
      didChange = true;
    }
  }

  if (typeof partial.opacity === 'number') {
    const nextOpacity = clampOpacity(partial.opacity);
    if (!Object.is(next.opacity, nextOpacity)) {
      next = { ...next, opacity: nextOpacity };
      didChange = true;
    }
  }

  if (typeof partial.visible === 'boolean' && partial.visible !== next.visible) {
    next = { ...next, visible: partial.visible };
    didChange = true;
  }

  if (typeof partial.zIndex === 'number' && isFiniteNumber(partial.zIndex)) {
    if (!Object.is(next.zIndex, partial.zIndex)) {
      next = { ...next, zIndex: partial.zIndex };
      didChange = true;
    }
  }

  if (!didChange) return;

  let nextLayers = layers.map((layer) => (layer.id === trimmedId ? next : layer));
  if (next.visible) {
    nextLayers = applyExclusiveVisibility(nextLayers, next.type, trimmedId);
  }

  replaceLayers(sortLayers(nextLayers));
};

const setLayerOpacity: LayerManagerState['setLayerOpacity'] = (id, opacity) => {
  updateLayer(id, { opacity });
};

const setLayerVisible: LayerManagerState['setLayerVisible'] = (id, visible) => {
  updateLayer(id, { visible });
};

const getLayersByType: LayerManagerState['getLayersByType'] = (type) =>
  layers.filter((layer) => layer.type === type);

const getVisibleLayers: LayerManagerState['getVisibleLayers'] = () =>
  layers.filter((layer) => layer.visible);

function getState(): LayerManagerState {
  return {
    layers,
    registerLayer,
    unregisterLayer,
    updateLayer,
    setLayerOpacity,
    setLayerVisible,
    getLayersByType,
    getVisibleLayers,
    batch,
  };
}

function setState(partial: Partial<Pick<LayerManagerState, 'layers'>>) {
  if (!partial.layers) return;

  const byId = new Map<string, LayerConfig>();
  for (const item of partial.layers) {
    const sanitized = sanitizeLayerConfig(item);
    if (!sanitized) continue;
    byId.set(sanitized.id, sanitized);
  }

  const normalized = enforceExclusivityOnLoad(Array.from(byId.values()));

  const isSame =
    normalized.length === layers.length &&
    normalized.every((layer, index) => layerConfigsEqual(layer, layers[index]!));
  if (isSame) return;

  replaceLayers(normalized);
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

type Selector<T> = (state: LayerManagerState) => T;

type StoreHook = {
  <T>(selector: Selector<T>): T;
  getState: typeof getState;
  setState: typeof setState;
};

const useLayerManagerStoreImpl = <T>(selector: Selector<T>): T =>
  useSyncExternalStore(
    subscribe,
    () => selector(getState()),
    () => selector(getState()),
  );

export const useLayerManagerStore: StoreHook = Object.assign(useLayerManagerStoreImpl, {
  getState,
  setState,
});
