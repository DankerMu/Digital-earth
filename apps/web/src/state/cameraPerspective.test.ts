import { act, render, screen } from '@testing-library/react';
import { createElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

const STORAGE_KEY = 'digital-earth.cameraPerspective';

async function importFresh() {
  vi.resetModules();
  return await import('./cameraPerspective');
}

function writeStorage(value: unknown) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
}

describe('cameraPerspective store', () => {
  it('defaults to free when localStorage is empty', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { DEFAULT_CAMERA_PERSPECTIVE_ID, useCameraPerspectiveStore } = await importFresh();

    const state = useCameraPerspectiveStore.getState();
    expect(state.cameraPerspectiveId).toBe(DEFAULT_CAMERA_PERSPECTIVE_ID);
    expect(state.cameraPerspectiveId).toBe('free');
  });

  it('restores a valid persisted cameraPerspectiveId', async () => {
    writeStorage({ cameraPerspectiveId: 'upward' });

    const { useCameraPerspectiveStore } = await importFresh();
    expect(useCameraPerspectiveStore.getState().cameraPerspectiveId).toBe('upward');
  });

  it('falls back to default when persisted JSON is invalid', async () => {
    localStorage.setItem(STORAGE_KEY, '{');
    const { useCameraPerspectiveStore } = await importFresh();
    expect(useCameraPerspectiveStore.getState().cameraPerspectiveId).toBe('free');
  });

  it('falls back to default when persisted JSON is not an object', async () => {
    localStorage.setItem(STORAGE_KEY, 'null');
    const { useCameraPerspectiveStore } = await importFresh();
    expect(useCameraPerspectiveStore.getState().cameraPerspectiveId).toBe('free');
  });

  it('falls back to default when persisted value is invalid', async () => {
    writeStorage({ cameraPerspectiveId: 'nope' });
    const { useCameraPerspectiveStore } = await importFresh();
    expect(useCameraPerspectiveStore.getState().cameraPerspectiveId).toBe('free');
  });

  it('setCameraPerspectiveId updates state and persists', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useCameraPerspectiveStore } = await importFresh();

    useCameraPerspectiveStore.getState().setCameraPerspectiveId('forward');
    expect(useCameraPerspectiveStore.getState().cameraPerspectiveId).toBe('forward');

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toEqual({ cameraPerspectiveId: 'forward' });
  });

  it('cycleCameraPerspective rotates forward → upward → free → forward', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useCameraPerspectiveStore } = await importFresh();

    useCameraPerspectiveStore.getState().setCameraPerspectiveId('forward');
    useCameraPerspectiveStore.getState().cycleCameraPerspective();
    expect(useCameraPerspectiveStore.getState().cameraPerspectiveId).toBe('upward');

    useCameraPerspectiveStore.getState().cycleCameraPerspective();
    expect(useCameraPerspectiveStore.getState().cameraPerspectiveId).toBe('free');

    useCameraPerspectiveStore.getState().cycleCameraPerspective();
    expect(useCameraPerspectiveStore.getState().cameraPerspectiveId).toBe('forward');
  });

  it('setState validates and persists partial updates', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useCameraPerspectiveStore } = await importFresh();

    useCameraPerspectiveStore.setState({ cameraPerspectiveId: 'upward' });
    expect(useCameraPerspectiveStore.getState().cameraPerspectiveId).toBe('upward');

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toEqual({ cameraPerspectiveId: 'upward' });
  });

  it('useCameraPerspectiveStore subscribes via useSyncExternalStore', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useCameraPerspectiveStore } = await importFresh();

    function PerspectiveLabel() {
      const cameraPerspectiveId = useCameraPerspectiveStore((state) => state.cameraPerspectiveId);
      return createElement('div', { 'data-testid': 'perspective' }, cameraPerspectiveId);
    }

    render(createElement(PerspectiveLabel));
    expect(screen.getByTestId('perspective')).toHaveTextContent('free');

    act(() => {
      useCameraPerspectiveStore.getState().setCameraPerspectiveId('upward');
    });

    expect(screen.getByTestId('perspective')).toHaveTextContent('upward');
  });

  it('handles localStorage read/write failures without throwing', async () => {
    localStorage.removeItem(STORAGE_KEY);

    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });

    const { useCameraPerspectiveStore } = await importFresh();
    expect(useCameraPerspectiveStore.getState().cameraPerspectiveId).toBe('free');
    getItem.mockRestore();

    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });

    expect(() => {
      useCameraPerspectiveStore.getState().setCameraPerspectiveId('forward');
    }).not.toThrow();
    expect(useCameraPerspectiveStore.getState().cameraPerspectiveId).toBe('forward');
    setItem.mockRestore();
  });
});

describe('isCameraPerspectiveId', () => {
  it('accepts only the supported ids', async () => {
    const { isCameraPerspectiveId } = await importFresh();

    expect(isCameraPerspectiveId('forward')).toBe(true);
    expect(isCameraPerspectiveId('upward')).toBe(true);
    expect(isCameraPerspectiveId('free')).toBe(true);

    expect(isCameraPerspectiveId('nope')).toBe(false);
    expect(isCameraPerspectiveId(123)).toBe(false);
    expect(isCameraPerspectiveId(null)).toBe(false);
  });
});

