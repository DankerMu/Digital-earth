import { act, render, screen } from '@testing-library/react';
import { createElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

const STORAGE_KEY = 'digital-earth.realLighting';

async function importFresh() {
  vi.resetModules();
  return await import('./realLighting');
}

function writeStorage(value: unknown) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
}

describe('realLighting store', () => {
  it('defaults to enabled when localStorage is empty', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useRealLightingStore } = await importFresh();
    expect(useRealLightingStore.getState().enabled).toBe(true);
  });

  it('restores a persisted enabled flag from an object record', async () => {
    writeStorage({ enabled: false });
    const { useRealLightingStore } = await importFresh();
    expect(useRealLightingStore.getState().enabled).toBe(false);
  });

  it('restores a persisted enabled flag from a boolean value', async () => {
    writeStorage(false);
    const { useRealLightingStore } = await importFresh();
    expect(useRealLightingStore.getState().enabled).toBe(false);
  });

  it('setEnabled updates state and persists', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useRealLightingStore } = await importFresh();

    useRealLightingStore.getState().setEnabled(false);
    expect(useRealLightingStore.getState().enabled).toBe(false);

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toEqual({ enabled: false });
  });

  it('toggleEnabled flips enabled', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useRealLightingStore } = await importFresh();

    expect(useRealLightingStore.getState().enabled).toBe(true);
    useRealLightingStore.getState().toggleEnabled();
    expect(useRealLightingStore.getState().enabled).toBe(false);
  });

  it('useRealLightingStore subscribes via useSyncExternalStore', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useRealLightingStore } = await importFresh();

    function EnabledLabel() {
      const enabled = useRealLightingStore((state) => state.enabled);
      return createElement('div', { 'data-testid': 'enabled' }, String(enabled));
    }

    render(createElement(EnabledLabel));
    expect(screen.getByTestId('enabled')).toHaveTextContent('true');

    act(() => {
      useRealLightingStore.getState().setEnabled(false);
    });

    expect(screen.getByTestId('enabled')).toHaveTextContent('false');
  });
});

