import { act, render, screen } from '@testing-library/react';
import { createElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const STORAGE_KEY = 'digital-earth.productDraft';

async function importFresh() {
  vi.resetModules();
  return await import('./productDraft');
}

function writeStorage(value: unknown) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
}

describe('productDraft store', () => {
  beforeEach(() => {
    localStorage.removeItem(STORAGE_KEY);
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T00:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('defaults to null when localStorage is empty', async () => {
    const { useProductDraftStore } = await importFresh();
    expect(useProductDraftStore.getState().draft).toBeNull();
    expect(useProductDraftStore.getState().updatedAt).toBeNull();
  });

  it('ignores malformed JSON in localStorage', async () => {
    localStorage.setItem(STORAGE_KEY, '{not-json');
    const { useProductDraftStore } = await importFresh();
    expect(useProductDraftStore.getState().draft).toBeNull();
  });

  it('restores a valid persisted draft', async () => {
    writeStorage({
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
    expect(useProductDraftStore.getState().draft).toEqual({
      title: 'T',
      text: 'Body',
      issued_at: '2026-01-01T00:00',
      valid_from: '2026-01-01T01:00',
      valid_to: '2026-01-01T02:00',
      type: 'snow',
      severity: 'low',
    });
    expect(useProductDraftStore.getState().updatedAt).toBe(123);
  });

  it('restores a draft and stamps updatedAt when missing', async () => {
    writeStorage({
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
    expect(useProductDraftStore.getState().draft?.title).toBe('T');
    expect(useProductDraftStore.getState().updatedAt).toBe(new Date('2026-01-01T00:00:00Z').getTime());
  });

  it('accepts a legacy persisted payload', async () => {
    writeStorage({
      title: 'Legacy',
      text: 'Body',
      issued_at: '2026-01-01T00:00',
      valid_from: '2026-01-01T01:00',
      valid_to: '2026-01-01T02:00',
      type: 'snow',
      severity: '',
    });

    const { useProductDraftStore } = await importFresh();
    expect(useProductDraftStore.getState().draft?.title).toBe('Legacy');
    expect(useProductDraftStore.getState().updatedAt).toBeTypeOf('number');
  });

  it('setState clears the draft when draft=null', async () => {
    const { useProductDraftStore } = await importFresh();

    useProductDraftStore.getState().setDraft({
      title: 'T',
      text: 'Body',
      issued_at: '2026-01-01T00:00',
      valid_from: '2026-01-01T01:00',
      valid_to: '2026-01-01T02:00',
      type: 'snow',
      severity: '',
    });

    useProductDraftStore.setState({ draft: null });
    expect(useProductDraftStore.getState().draft).toBeNull();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('setState sets draft and persists', async () => {
    const { useProductDraftStore } = await importFresh();

    useProductDraftStore.setState({
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

    expect(useProductDraftStore.getState().draft?.title).toBe('From setState');
    expect(localStorage.getItem(STORAGE_KEY)).not.toBeNull();
  });

  it('setState updates updatedAt and persists', async () => {
    const { useProductDraftStore } = await importFresh();

    useProductDraftStore.getState().setDraft({
      title: 'T',
      text: 'Body',
      issued_at: '2026-01-01T00:00',
      valid_from: '2026-01-01T01:00',
      valid_to: '2026-01-01T02:00',
      type: 'snow',
      severity: '',
    });

    useProductDraftStore.setState({ updatedAt: 999 });
    expect(useProductDraftStore.getState().updatedAt).toBe(999);

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toMatchObject({ updatedAt: 999 });
  });

  it('setDraft updates state and persists', async () => {
    const { useProductDraftStore } = await importFresh();

    useProductDraftStore.getState().setDraft({
      title: 'T',
      text: 'Body',
      issued_at: '2026-01-01T00:00',
      valid_from: '2026-01-01T01:00',
      valid_to: '2026-01-01T02:00',
      type: 'snow',
      severity: '',
    });

    expect(useProductDraftStore.getState().draft?.title).toBe('T');

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
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
      useProductDraftStore.getState().setDraft(null as unknown as any);
    }).not.toThrow();

    expect(useProductDraftStore.getState().draft).toBeNull();
  });

  it('clearDraft is a no-op when already cleared', async () => {
    const { useProductDraftStore } = await importFresh();
    expect(() => useProductDraftStore.getState().clearDraft()).not.toThrow();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('ignores localStorage write failures', async () => {
    const { useProductDraftStore } = await importFresh();
    const setItemSpy = vi
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => {
        throw new Error('blocked');
      });

    expect(() => {
      useProductDraftStore.getState().setDraft({
        title: 'T',
        text: 'Body',
        issued_at: '2026-01-01T00:00',
        valid_from: '2026-01-01T01:00',
        valid_to: '2026-01-01T02:00',
        type: 'snow',
        severity: '',
      });
    }).not.toThrow();

    expect(useProductDraftStore.getState().draft?.title).toBe('T');
    setItemSpy.mockRestore();
  });

  it('patchDraft creates a draft when empty and persists', async () => {
    const { useProductDraftStore } = await importFresh();

    useProductDraftStore.getState().patchDraft({ title: 'Patched', severity: 'high' });
    expect(useProductDraftStore.getState().draft).toEqual({
      title: 'Patched',
      text: '',
      issued_at: '',
      valid_from: '',
      valid_to: '',
      type: '',
      severity: 'high',
    });

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toMatchObject({
      draft: { title: 'Patched', severity: 'high' },
    });
  });

  it('clearDraft removes persisted storage', async () => {
    const { useProductDraftStore } = await importFresh();

    useProductDraftStore.getState().setDraft({
      title: 'T',
      text: 'Body',
      issued_at: '2026-01-01T00:00',
      valid_from: '2026-01-01T01:00',
      valid_to: '2026-01-01T02:00',
      type: 'snow',
      severity: '',
    });

    useProductDraftStore.getState().clearDraft();
    expect(useProductDraftStore.getState().draft).toBeNull();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('useProductDraftStore subscribes via useSyncExternalStore', async () => {
    const { useProductDraftStore } = await importFresh();

    function DraftTitle() {
      const draftTitle = useProductDraftStore((state) => state.draft?.title ?? 'none');
      return createElement('div', { 'data-testid': 'title' }, draftTitle);
    }

    render(createElement(DraftTitle));
    expect(screen.getByTestId('title')).toHaveTextContent('none');

    act(() => {
      useProductDraftStore.getState().patchDraft({ title: 'Updated' });
    });

    expect(screen.getByTestId('title')).toHaveTextContent('Updated');
  });
});
