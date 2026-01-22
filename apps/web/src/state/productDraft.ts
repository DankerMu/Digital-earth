import { useSyncExternalStore } from 'react';

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

const STORAGE_KEY = 'digital-earth.productDraft';

type Listener = () => void;

const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) listener();
}

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
  };
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

function safeReadPersistedDraft(): PersistedProductDraft | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    return parsePersistedProductDraft(parsed);
  } catch {
    return null;
  }
}

function safeWritePersistedDraft(value: PersistedProductDraft | null) {
  try {
    if (!value) {
      localStorage.removeItem(STORAGE_KEY);
      return;
    }

    localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // ignore write failures (e.g., disabled storage)
  }
}

const persisted = safeReadPersistedDraft();
let draft: ProductDraft | null = persisted?.draft ?? null;
let updatedAt: number | null = persisted?.updatedAt ?? null;

function persist() {
  if (!draft || updatedAt == null) {
    safeWritePersistedDraft(null);
    return;
  }

  safeWritePersistedDraft({ draft, updatedAt });
}

const setDraft: ProductDraftState['setDraft'] = (next) => {
  const parsed = parseProductDraft(next);
  if (!parsed) return;
  draft = parsed;
  updatedAt = Date.now();
  persist();
  notify();
};

const patchDraft: ProductDraftState['patchDraft'] = (patch) => {
  const current = draft ?? createEmptyProductDraft();
  draft = { ...current, ...patch };
  updatedAt = Date.now();
  persist();
  notify();
};

const clearDraft: ProductDraftState['clearDraft'] = () => {
  if (draft == null && updatedAt == null) return;
  draft = null;
  updatedAt = null;
  persist();
  notify();
};

function getState(): ProductDraftState {
  return { draft, updatedAt, setDraft, patchDraft, clearDraft };
}

function setState(partial: Partial<Pick<ProductDraftState, 'draft' | 'updatedAt'>>) {
  if ('draft' in partial) {
    const nextDraft = partial.draft;
    if (nextDraft == null) {
      clearDraft();
      return;
    }
    setDraft(nextDraft);
    return;
  }

  if (typeof partial.updatedAt === 'number' && Number.isFinite(partial.updatedAt) && partial.updatedAt >= 0) {
    updatedAt = partial.updatedAt;
    persist();
    notify();
  }
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

type Selector<T> = (state: ProductDraftState) => T;

type StoreHook = {
  <T>(selector: Selector<T>): T;
  getState: typeof getState;
  setState: typeof setState;
};

const useProductDraftStoreImpl = <T>(selector: Selector<T>): T =>
  useSyncExternalStore(
    subscribe,
    () => selector(getState()),
    () => selector(getState()),
  );

export const useProductDraftStore: StoreHook = Object.assign(useProductDraftStoreImpl, {
  getState,
  setState,
});
