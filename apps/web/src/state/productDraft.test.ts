import { act, render, screen } from '@testing-library/react';
import { createElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ProductDraft } from './productDraft';

const LEGACY_STORAGE_KEY = 'digital-earth.productDraft';
const NEW_STORAGE_KEY = 'digital-earth.productDraft.new';
const PRODUCT_STORAGE_KEY = 'digital-earth.productDraft.123';

async function importFresh() {
  vi.resetModules();
  return await import('./productDraft');
}

function writeStorage(storageKey: string, value: unknown) {
  localStorage.setItem(storageKey, JSON.stringify(value));
}

describe('productDraft store', () => {
  beforeEach(() => {
    localStorage.removeItem(LEGACY_STORAGE_KEY);
    localStorage.removeItem(NEW_STORAGE_KEY);
    localStorage.removeItem(PRODUCT_STORAGE_KEY);
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T00:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('defaults to null when localStorage is empty', async () => {
    const { useProductDraftStore } = await importFresh();
    expect(useProductDraftStore.getState(NEW_STORAGE_KEY).draft).toBeNull();
    expect(useProductDraftStore.getState(NEW_STORAGE_KEY).updatedAt).toBeNull();
  });

  it('ignores malformed JSON in localStorage', async () => {
    localStorage.setItem(NEW_STORAGE_KEY, '{not-json');
    const { useProductDraftStore } = await importFresh();
    expect(useProductDraftStore.getState(NEW_STORAGE_KEY).draft).toBeNull();
  });

  it('restores a valid persisted draft', async () => {
    writeStorage(NEW_STORAGE_KEY, {
      draft: {
        title: 'T',
        text: 'Body',
        issued_at: '2026-01-01T00:00',
        valid_from: '2026-01-01T01:00',
        valid_to: '2026-01-01T02:00',
        type: 'snow',
        severity: 'low',
      },
      updatedAt: 123,
    });

    const { useProductDraftStore } = await importFresh();
    expect(useProductDraftStore.getState(NEW_STORAGE_KEY).draft).toEqual({
      title: 'T',
      text: 'Body',
      issued_at: '2026-01-01T00:00',
      valid_from: '2026-01-01T01:00',
      valid_to: '2026-01-01T02:00',
      type: 'snow',
      severity: 'low',
    });
    expect(useProductDraftStore.getState(NEW_STORAGE_KEY).updatedAt).toBe(123);
  });

  it('restores a draft and stamps updatedAt when missing', async () => {
    writeStorage(NEW_STORAGE_KEY, {
      draft: {
        title: 'T',
        text: 'Body',
        issued_at: '2026-01-01T00:00',
        valid_from: '2026-01-01T01:00',
        valid_to: '2026-01-01T02:00',
        type: 'snow',
        severity: '',
      },
      updatedAt: null,
    });

    const { useProductDraftStore } = await importFresh();
    expect(useProductDraftStore.getState(NEW_STORAGE_KEY).draft?.title).toBe('T');
    expect(useProductDraftStore.getState(NEW_STORAGE_KEY).updatedAt).toBe(new Date('2026-01-01T00:00:00Z').getTime());
  });

  it('migrates from legacy storage when present', async () => {
    writeStorage(LEGACY_STORAGE_KEY, {
      title: 'Legacy',
      text: 'Body',
      issued_at: '2026-01-01T00:00',
      valid_from: '2026-01-01T01:00',
      valid_to: '2026-01-01T02:00',
      type: 'snow',
      severity: '',
    });

    const { useProductDraftStore } = await importFresh();
    expect(useProductDraftStore.getState(NEW_STORAGE_KEY).draft?.title).toBe('Legacy');
    expect(useProductDraftStore.getState(NEW_STORAGE_KEY).updatedAt).toBeTypeOf('number');
    expect(localStorage.getItem(LEGACY_STORAGE_KEY)).toBeNull();
    expect(localStorage.getItem(NEW_STORAGE_KEY)).not.toBeNull();
  });

  it('setState clears the draft when draft=null', async () => {
    const { useProductDraftStore } = await importFresh();

    useProductDraftStore.getState(NEW_STORAGE_KEY).setDraft({
      title: 'T',
      text: 'Body',
      issued_at: '2026-01-01T00:00',
      valid_from: '2026-01-01T01:00',
      valid_to: '2026-01-01T02:00',
      type: 'snow',
      severity: '',
    });

    useProductDraftStore.setState(NEW_STORAGE_KEY, { draft: null });
    expect(useProductDraftStore.getState(NEW_STORAGE_KEY).draft).toBeNull();
    expect(localStorage.getItem(NEW_STORAGE_KEY)).toBeNull();
  });

  it('setState sets draft and persists', async () => {
    const { useProductDraftStore } = await importFresh();

    useProductDraftStore.setState(NEW_STORAGE_KEY, {
      draft: {
        title: 'From setState',
        text: 'Body',
        issued_at: '2026-01-01T00:00',
        valid_from: '2026-01-01T01:00',
        valid_to: '2026-01-01T02:00',
        type: 'snow',
        severity: '',
      },
    });

    expect(useProductDraftStore.getState(NEW_STORAGE_KEY).draft?.title).toBe('From setState');
    expect(localStorage.getItem(NEW_STORAGE_KEY)).not.toBeNull();
  });

  it('setState updates updatedAt and persists', async () => {
    const { useProductDraftStore } = await importFresh();

    useProductDraftStore.getState(NEW_STORAGE_KEY).setDraft({
      title: 'T',
      text: 'Body',
      issued_at: '2026-01-01T00:00',
      valid_from: '2026-01-01T01:00',
      valid_to: '2026-01-01T02:00',
      type: 'snow',
      severity: '',
    });

    useProductDraftStore.setState(NEW_STORAGE_KEY, { updatedAt: 999 });
    expect(useProductDraftStore.getState(NEW_STORAGE_KEY).updatedAt).toBe(999);

    const persisted = JSON.parse(localStorage.getItem(NEW_STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toMatchObject({ updatedAt: 999 });
  });

  it('setDraft updates state and persists', async () => {
    const { useProductDraftStore } = await importFresh();

    useProductDraftStore.getState(NEW_STORAGE_KEY).setDraft({
      title: 'T',
      text: 'Body',
      issued_at: '2026-01-01T00:00',
      valid_from: '2026-01-01T01:00',
      valid_to: '2026-01-01T02:00',
      type: 'snow',
      severity: '',
    });

    expect(useProductDraftStore.getState(NEW_STORAGE_KEY).draft?.title).toBe('T');

    const persisted = JSON.parse(localStorage.getItem(NEW_STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toEqual({
      draft: {
        title: 'T',
        text: 'Body',
        issued_at: '2026-01-01T00:00',
        valid_from: '2026-01-01T01:00',
        valid_to: '2026-01-01T02:00',
        type: 'snow',
        severity: '',
      },
      updatedAt: new Date('2026-01-01T00:00:00Z').getTime(),
    });
  });

  it('setDraft ignores invalid payloads', async () => {
    const { useProductDraftStore } = await importFresh();

    expect(() => {
      useProductDraftStore.getState(NEW_STORAGE_KEY).setDraft(null as unknown as ProductDraft);
    }).not.toThrow();

    expect(useProductDraftStore.getState(NEW_STORAGE_KEY).draft).toBeNull();
  });

  it('clearDraft is a no-op when already cleared', async () => {
    const { useProductDraftStore } = await importFresh();
    expect(() => useProductDraftStore.getState(NEW_STORAGE_KEY).clearDraft()).not.toThrow();
    expect(localStorage.getItem(NEW_STORAGE_KEY)).toBeNull();
  });

  it('ignores localStorage write failures', async () => {
    const { useProductDraftStore } = await importFresh();
    const setItemSpy = vi
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => {
        throw new Error('blocked');
      });

    expect(() => {
      useProductDraftStore.getState(NEW_STORAGE_KEY).setDraft({
        title: 'T',
        text: 'Body',
        issued_at: '2026-01-01T00:00',
        valid_from: '2026-01-01T01:00',
        valid_to: '2026-01-01T02:00',
        type: 'snow',
        severity: '',
      });
    }).not.toThrow();

    expect(useProductDraftStore.getState(NEW_STORAGE_KEY).draft?.title).toBe('T');
    setItemSpy.mockRestore();
  });

  it('patchDraft creates a draft when empty and persists', async () => {
    const { useProductDraftStore } = await importFresh();

    useProductDraftStore.getState(NEW_STORAGE_KEY).patchDraft({ title: 'Patched', severity: 'high' });
    expect(useProductDraftStore.getState(NEW_STORAGE_KEY).draft).toEqual({
      title: 'Patched',
      text: '',
      issued_at: '',
      valid_from: '',
      valid_to: '',
      type: '',
      severity: 'high',
    });

    const persisted = JSON.parse(localStorage.getItem(NEW_STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toMatchObject({
      draft: { title: 'Patched', severity: 'high' },
    });
  });

  it('clearDraft removes persisted storage', async () => {
    const { useProductDraftStore } = await importFresh();

    useProductDraftStore.getState(NEW_STORAGE_KEY).setDraft({
      title: 'T',
      text: 'Body',
      issued_at: '2026-01-01T00:00',
      valid_from: '2026-01-01T01:00',
      valid_to: '2026-01-01T02:00',
      type: 'snow',
      severity: '',
    });

    useProductDraftStore.getState(NEW_STORAGE_KEY).clearDraft();
    expect(useProductDraftStore.getState(NEW_STORAGE_KEY).draft).toBeNull();
    expect(localStorage.getItem(NEW_STORAGE_KEY)).toBeNull();
  });

  it('isolates drafts between different storage keys', async () => {
    const { useProductDraftStore } = await importFresh();

    useProductDraftStore.getState(NEW_STORAGE_KEY).setDraft({
      title: 'New Draft',
      text: 'Body',
      issued_at: '2026-01-01T00:00',
      valid_from: '2026-01-01T01:00',
      valid_to: '2026-01-01T02:00',
      type: 'snow',
      severity: '',
    });

    useProductDraftStore.getState(PRODUCT_STORAGE_KEY).setDraft({
      title: 'Existing Draft',
      text: 'Body',
      issued_at: '2026-01-02T00:00',
      valid_from: '2026-01-02T01:00',
      valid_to: '2026-01-02T02:00',
      type: 'rain',
      severity: 'high',
    });

    expect(useProductDraftStore.getState(NEW_STORAGE_KEY).draft?.title).toBe('New Draft');
    expect(useProductDraftStore.getState(PRODUCT_STORAGE_KEY).draft?.title).toBe('Existing Draft');
  });

  it('useProductDraftStore subscribes via useSyncExternalStore', async () => {
    const { useProductDraftStore } = await importFresh();

    function DraftTitle() {
      const draftTitle = useProductDraftStore(NEW_STORAGE_KEY, (state) => state.draft?.title ?? 'none');
      return createElement('div', { 'data-testid': 'title' }, draftTitle);
    }

    render(createElement(DraftTitle));
    expect(screen.getByTestId('title')).toHaveTextContent('none');

    act(() => {
      useProductDraftStore.getState(NEW_STORAGE_KEY).patchDraft({ title: 'Updated' });
    });

    expect(screen.getByTestId('title')).toHaveTextContent('Updated');
  });
});
