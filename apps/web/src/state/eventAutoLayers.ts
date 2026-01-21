import { useSyncExternalStore } from 'react';

export type EventLayerTemplate = string[];

export type EventLayerTemplateSpec = Array<string | string[]>;

export type EventAutoLayersState = {
  restoreOnExit: boolean;
  overrides: Record<string, EventLayerTemplate>;
  setRestoreOnExit: (restoreOnExit: boolean) => void;
  setOverride: (eventType: string, template: EventLayerTemplate) => void;
  clearOverride: (eventType: string) => void;
  getTemplateSpecForEvent: (eventType: string) => EventLayerTemplateSpec | null;
  getTemplateForEvent: (eventType: string, availableLayerIds: string[]) => string[];
};

const STORAGE_KEY = 'digital-earth.eventAutoLayers';

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

function normalizeKey(value: string): string {
  return value.trim().toLowerCase();
}

export function canonicalizeEventType(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '';

  const lower = normalizeKey(trimmed);
  if (lower === 'snow' || lower.includes('snow')) return 'snow';
  if (trimmed.includes('雪')) return 'snow';

  return lower;
}

function sanitizeTemplate(value: unknown): EventLayerTemplate {
  if (!Array.isArray(value)) return [];

  const seen = new Set<string>();
  const next: string[] = [];

  for (const entry of value) {
    if (!isNonEmptyString(entry)) continue;
    const id = entry.trim();
    if (seen.has(id)) continue;
    seen.add(id);
    next.push(id);
  }

  return next;
}

function sanitizeOverrides(value: unknown): Record<string, EventLayerTemplate> {
  if (!isRecord(value)) return {};

  const next: Record<string, EventLayerTemplate> = {};
  for (const [rawType, rawTemplate] of Object.entries(value)) {
    if (!isNonEmptyString(rawType)) continue;
    const key = canonicalizeEventType(rawType);
    if (!key) continue;
    const template = sanitizeTemplate(rawTemplate);
    if (template.length === 0) continue;
    next[key] = template;
  }
  return next;
}

type PersistedState = {
  restoreOnExit?: unknown;
  overrides?: unknown;
};

function safeReadPersisted(): PersistedState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!isRecord(parsed)) return {};
    return parsed as PersistedState;
  } catch {
    return {};
  }
}

function safeWritePersisted(next: { restoreOnExit: boolean; overrides: Record<string, EventLayerTemplate> }) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // ignore write failures (e.g., disabled storage)
  }
}

const DEFAULT_TEMPLATES: Record<string, EventLayerTemplateSpec> = {
  snow: [
    'precipitation',
    'temperature',
    'cloud',
    ['snow-depth', 'snowDepth', 'snow_depth', 'snowdepth'],
  ],
};

export function resolveEventLayerTemplateSpec(
  spec: EventLayerTemplateSpec,
  availableLayerIds: string[],
): string[] {
  const available = new Set(
    availableLayerIds
      .filter((id) => typeof id === 'string')
      .map((id) => id.trim())
      .filter((id) => id.length > 0),
  );

  const next: string[] = [];
  const seen = new Set<string>();

  for (const entry of spec) {
    if (typeof entry === 'string') {
      const id = entry.trim();
      if (!id) continue;
      if (!available.has(id)) continue;
      if (seen.has(id)) continue;
      seen.add(id);
      next.push(id);
      continue;
    }

    if (!Array.isArray(entry)) continue;

    const candidate = entry.map((id) => id.trim()).find((id) => id && available.has(id));
    if (!candidate) continue;
    if (seen.has(candidate)) continue;
    seen.add(candidate);
    next.push(candidate);
  }

  return next;
}

function getTemplateSpec(options: {
  eventType: string;
  overrides: Record<string, EventLayerTemplate>;
}): EventLayerTemplateSpec | null {
  const canonicalType = canonicalizeEventType(options.eventType);
  if (!canonicalType) return null;

  const override = options.overrides[canonicalType];
  if (override) {
    return override;
  }

  const spec = DEFAULT_TEMPLATES[canonicalType];
  return spec ?? null;
}

const persisted = safeReadPersisted();

let restoreOnExit = persisted.restoreOnExit !== false;
let overrides = sanitizeOverrides(persisted.overrides);

const setRestoreOnExit: EventAutoLayersState['setRestoreOnExit'] = (next) => {
  if (typeof next !== 'boolean') return;
  if (Object.is(restoreOnExit, next)) return;
  restoreOnExit = next;
  safeWritePersisted({ restoreOnExit, overrides });
  notify();
};

const setOverride: EventAutoLayersState['setOverride'] = (eventType, template) => {
  if (!isNonEmptyString(eventType)) return;
  const key = canonicalizeEventType(eventType);
  if (!key) return;
  const sanitized = sanitizeTemplate(template);

  const nextOverrides = { ...overrides };
  if (sanitized.length === 0) {
    if (!(key in nextOverrides)) return;
    delete nextOverrides[key];
  } else {
    nextOverrides[key] = sanitized;
  }

  overrides = nextOverrides;
  safeWritePersisted({ restoreOnExit, overrides });
  notify();
};

const clearOverride: EventAutoLayersState['clearOverride'] = (eventType) => {
  if (!isNonEmptyString(eventType)) return;
  const key = canonicalizeEventType(eventType);
  if (!key) return;
  if (!(key in overrides)) return;
  const nextOverrides = { ...overrides };
  delete nextOverrides[key];
  overrides = nextOverrides;
  safeWritePersisted({ restoreOnExit, overrides });
  notify();
};

const getTemplateSpecForEvent: EventAutoLayersState['getTemplateSpecForEvent'] = (eventType) => {
  return getTemplateSpec({ eventType, overrides });
};

const getTemplateForEvent: EventAutoLayersState['getTemplateForEvent'] = (eventType, availableLayerIds) => {
  if (!Array.isArray(availableLayerIds)) return [];
  const spec = getTemplateSpec({ eventType, overrides });
  if (!spec) return [];
  return resolveEventLayerTemplateSpec(spec, availableLayerIds);
};

function getState(): EventAutoLayersState {
  return {
    restoreOnExit,
    overrides,
    setRestoreOnExit,
    setOverride,
    clearOverride,
    getTemplateSpecForEvent,
    getTemplateForEvent,
  };
}

function setState(
  partial: Partial<Pick<EventAutoLayersState, 'restoreOnExit' | 'overrides'>>,
) {
  let didChange = false;

  if (typeof partial.restoreOnExit === 'boolean' && !Object.is(restoreOnExit, partial.restoreOnExit)) {
    restoreOnExit = partial.restoreOnExit;
    didChange = true;
  }

  if (partial.overrides && isRecord(partial.overrides)) {
    const nextOverrides = sanitizeOverrides(partial.overrides);
    const keys = Object.keys(nextOverrides);
    const currentKeys = Object.keys(overrides);
    const isSame =
      keys.length === currentKeys.length &&
      keys.every((key) =>
        overrides[key]?.length === nextOverrides[key]?.length &&
        overrides[key]?.every((id, idx) => id === nextOverrides[key]?.[idx]),
      );
    if (!isSame) {
      overrides = nextOverrides;
      didChange = true;
    }
  }

  if (!didChange) return;
  safeWritePersisted({ restoreOnExit, overrides });
  notify();
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

type Selector<T> = (state: EventAutoLayersState) => T;

type StoreHook = {
  <T>(selector: Selector<T>): T;
  getState: typeof getState;
  setState: typeof setState;
};

const useEventAutoLayersStoreImpl = <T>(selector: Selector<T>): T =>
  useSyncExternalStore(
    subscribe,
    () => selector(getState()),
    () => selector(getState()),
  );

export const useEventAutoLayersStore: StoreHook = Object.assign(useEventAutoLayersStoreImpl, {
  getState,
  setState,
});
