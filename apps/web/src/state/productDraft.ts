import { useSyncExternalStore } from 'react';

import type { LonLat } from '../lib/geo';

export type ProductHazardDraft = {
  /**
   * Client-generated stable identifier used for editing/picking.
   * Not necessarily the backend hazard id.
   */
  id: string;
  vertices: LonLat[];
};

export type ProductDraft = {
  title: string;
  text: string;
  issued_at: string;
  valid_from: string;
  valid_to: string;
  type: string;
  /**
   * Optional severity label for the product (e.g. "low" | "medium" | "high").
   * An empty string means unset.
   */
  severity: string;
  hazards: ProductHazardDraft[];
};

type PersistedProductDraft = {
  draft: ProductDraft;
  updatedAt: number;
};

type ProductDraftState = {
  draft: ProductDraft | null;
  updatedAt: number | null;
  setDraft: (draft: ProductDraft) => void;
  patchDraft: (draft: Partial<ProductDraft>) => void;
  clearDraft: () => void;
};

const LEGACY_STORAGE_KEY = 'digital-earth.productDraft';
const STORAGE_KEY_PREFIX = 'digital-earth.productDraft.';
const NEW_PRODUCT_DRAFT_KEY = `${STORAGE_KEY_PREFIX}new`;

export function getProductDraftStorageKey(productId?: string | number | null): string {
  const normalized =
    typeof productId === 'number'
      ? String(productId)
      : typeof productId === 'string'
        ? productId.trim()
        : '';

  if (!normalized) return NEW_PRODUCT_DRAFT_KEY;
  return `${STORAGE_KEY_PREFIX}${normalized}`;
}

type Listener = () => void;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

function normalizeString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

export function createEmptyProductDraft(): ProductDraft {
  return {
    title: '',
    text: '',
    issued_at: '',
    valid_from: '',
    valid_to: '',
    type: '',
    severity: '',
    hazards: [],
  };
}

function normalizeFiniteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function parseHazardVertex(value: unknown): LonLat | null {
  if (!isRecord(value)) return null;
  const lon = normalizeFiniteNumber(value.lon);
  const lat = normalizeFiniteNumber(value.lat);
  if (lon == null || lat == null) return null;
  return { lon, lat };
}

function parseHazardDraft(value: unknown): ProductHazardDraft | null {
  if (!isRecord(value)) return null;
  const id = normalizeString(value.id).trim();
  if (!id) return null;
  const verticesRaw = value.vertices;
  const vertices = Array.isArray(verticesRaw)
    ? verticesRaw.map(parseHazardVertex).filter((vertex): vertex is LonLat => vertex != null)
    : [];
  return { id, vertices };
}

function parseProductDraft(value: unknown): ProductDraft | null {
  if (!isRecord(value)) return null;

  return {
    title: normalizeString(value.title),
    text: normalizeString(value.text),
    issued_at: normalizeString(value.issued_at),
    valid_from: normalizeString(value.valid_from),
    valid_to: normalizeString(value.valid_to),
    type: normalizeString(value.type),
    severity: normalizeString(value.severity),
    hazards: Array.isArray(value.hazards)
      ? value.hazards
          .map(parseHazardDraft)
          .filter((hazard): hazard is ProductHazardDraft => hazard != null)
      : [],
  };
}

function parsePersistedProductDraft(value: unknown): PersistedProductDraft | null {
  if (!isRecord(value)) return null;

  const updatedAt = value.updatedAt;
  const updatedAtNumber = typeof updatedAt === 'number' && Number.isFinite(updatedAt) ? updatedAt : null;

  const draft = parseProductDraft(value.draft);
  if (!draft) {
    // Backwards-compatible: accept legacy payloads storing the draft directly.
    const legacyDraft = parseProductDraft(value);
    if (!legacyDraft) return null;
    return { draft: legacyDraft, updatedAt: updatedAtNumber ?? Date.now() };
  }

  if (updatedAtNumber == null) return { draft, updatedAt: Date.now() };
  return { draft, updatedAt: updatedAtNumber };
}

function safeReadPersistedDraft(storageKey: string): PersistedProductDraft | null {
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    return parsePersistedProductDraft(parsed);
  } catch {
    return null;
  }
}

function safeWritePersistedDraft(storageKey: string, value: PersistedProductDraft | null) {
  try {
    if (!value) {
      localStorage.removeItem(storageKey);
      return;
    }

    localStorage.setItem(storageKey, JSON.stringify(value));
  } catch {
    // ignore write failures (e.g., disabled storage)
  }
}

type StoreEntry = {
  storageKey: string;
  draft: ProductDraft | null;
  updatedAt: number | null;
  listeners: Set<Listener>;
  setDraft: ProductDraftState['setDraft'];
  patchDraft: ProductDraftState['patchDraft'];
  clearDraft: ProductDraftState['clearDraft'];
};

const stores = new Map<string, StoreEntry>();

function notify(store: StoreEntry) {
  for (const listener of store.listeners) listener();
}

function persist(store: StoreEntry) {
  if (!store.draft || store.updatedAt == null) {
    safeWritePersistedDraft(store.storageKey, null);
    if (store.storageKey === NEW_PRODUCT_DRAFT_KEY) {
      safeWritePersistedDraft(LEGACY_STORAGE_KEY, null);
    }
    return;
  }

  safeWritePersistedDraft(store.storageKey, { draft: store.draft, updatedAt: store.updatedAt });
  if (store.storageKey === NEW_PRODUCT_DRAFT_KEY) {
    safeWritePersistedDraft(LEGACY_STORAGE_KEY, null);
  }
}

function createStoreEntry(storageKey: string): StoreEntry {
  let persisted = safeReadPersistedDraft(storageKey);
  if (!persisted && storageKey === NEW_PRODUCT_DRAFT_KEY) {
    persisted = safeReadPersistedDraft(LEGACY_STORAGE_KEY);
    if (persisted) {
      safeWritePersistedDraft(storageKey, persisted);
      safeWritePersistedDraft(LEGACY_STORAGE_KEY, null);
    }
  }

  const store: StoreEntry = {
    storageKey,
    draft: persisted?.draft ?? null,
    updatedAt: persisted?.updatedAt ?? null,
    listeners: new Set<Listener>(),
    setDraft: () => {},
    patchDraft: () => {},
    clearDraft: () => {},
  };

  store.setDraft = (next) => {
    const parsed = parseProductDraft(next);
    if (!parsed) return;
    store.draft = parsed;
    store.updatedAt = Date.now();
    persist(store);
    notify(store);
  };

  store.patchDraft = (patch) => {
    const current = store.draft ?? createEmptyProductDraft();
    store.draft = { ...current, ...patch };
    store.updatedAt = Date.now();
    persist(store);
    notify(store);
  };

  store.clearDraft = () => {
    if (store.draft == null && store.updatedAt == null) return;
    store.draft = null;
    store.updatedAt = null;
    persist(store);
    notify(store);
  };

  return store;
}

function getStoreEntry(storageKey: string): StoreEntry {
  const normalizedKey = storageKey.trim();
  const key = normalizedKey.length > 0 ? normalizedKey : NEW_PRODUCT_DRAFT_KEY;
  const existing = stores.get(key);
  if (existing) return existing;
  const created = createStoreEntry(key);
  stores.set(key, created);
  return created;
}

function getState(storageKey: string): ProductDraftState {
  const store = getStoreEntry(storageKey);
  return {
    draft: store.draft,
    updatedAt: store.updatedAt,
    setDraft: store.setDraft,
    patchDraft: store.patchDraft,
    clearDraft: store.clearDraft,
  };
}

function setState(storageKey: string, partial: Partial<Pick<ProductDraftState, 'draft' | 'updatedAt'>>) {
  const store = getStoreEntry(storageKey);

  if ('draft' in partial) {
    const nextDraft = partial.draft;
    if (nextDraft == null) {
      store.clearDraft();
      return;
    }
    store.setDraft(nextDraft);
    return;
  }

  if (typeof partial.updatedAt === 'number' && Number.isFinite(partial.updatedAt) && partial.updatedAt >= 0) {
    store.updatedAt = partial.updatedAt;
    persist(store);
    notify(store);
  }
}

function subscribe(storageKey: string, listener: Listener) {
  const store = getStoreEntry(storageKey);
  store.listeners.add(listener);
  return () => {
    store.listeners.delete(listener);
  };
}

type Selector<T> = (state: ProductDraftState) => T;

type StoreHook = {
  <T>(storageKey: string, selector: Selector<T>): T;
  getState: (storageKey: string) => ProductDraftState;
  setState: (storageKey: string, partial: Partial<Pick<ProductDraftState, 'draft' | 'updatedAt'>>) => void;
};

const useProductDraftStoreImpl = <T>(storageKey: string, selector: Selector<T>): T =>
  useSyncExternalStore(
    (listener) => subscribe(storageKey, listener),
    () => selector(getState(storageKey)),
    () => selector(getState(storageKey)),
  );

export const useProductDraftStore: StoreHook = Object.assign(useProductDraftStoreImpl, {
  getState,
  setState,
});
