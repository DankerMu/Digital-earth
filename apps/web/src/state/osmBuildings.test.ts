import { act, render, screen } from '@testing-library/react';
import { createElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

const STORAGE_KEY = 'digital-earth.osmBuildings';

async function importFresh() {
  vi.resetModules();
  return await import('./osmBuildings');
}

function writeStorage(value: unknown) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
}

describe('osmBuildings store', () => {
  it('defaults to enabled when localStorage is empty', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useOsmBuildingsStore } = await importFresh();
    expect(useOsmBuildingsStore.getState().enabled).toBe(true);
  });

  it('restores a persisted enabled flag', async () => {
    writeStorage({ enabled: false });
    const { useOsmBuildingsStore } = await importFresh();
    expect(useOsmBuildingsStore.getState().enabled).toBe(false);
  });

  it('setEnabled updates state and persists', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useOsmBuildingsStore } = await importFresh();

    useOsmBuildingsStore.getState().setEnabled(false);
    expect(useOsmBuildingsStore.getState().enabled).toBe(false);

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toEqual({ enabled: false });
  });

  it('toggleEnabled flips enabled', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useOsmBuildingsStore } = await importFresh();

    expect(useOsmBuildingsStore.getState().enabled).toBe(true);
    useOsmBuildingsStore.getState().toggleEnabled();
    expect(useOsmBuildingsStore.getState().enabled).toBe(false);
  });

  it('useOsmBuildingsStore subscribes via useSyncExternalStore', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useOsmBuildingsStore } = await importFresh();

    function EnabledLabel() {
      const enabled = useOsmBuildingsStore((state) => state.enabled);
      return createElement('div', { 'data-testid': 'enabled' }, String(enabled));
    }

    render(createElement(EnabledLabel));
    expect(screen.getByTestId('enabled')).toHaveTextContent('true');

    act(() => {
      useOsmBuildingsStore.getState().setEnabled(false);
    });

    expect(screen.getByTestId('enabled')).toHaveTextContent('false');
  });
});

