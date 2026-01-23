import { act, render, screen } from '@testing-library/react';
import { createElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

const STORAGE_KEY = 'digital-earth.aircraftDemo';

async function importFresh() {
  vi.resetModules();
  return await import('./aircraftDemo');
}

function writeStorage(value: unknown) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
}

describe('aircraftDemo store', () => {
  it('defaults to disabled when localStorage is empty', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useAircraftDemoStore } = await importFresh();
    expect(useAircraftDemoStore.getState().enabled).toBe(false);
  });

  it('restores a persisted enabled flag', async () => {
    writeStorage({ enabled: true });
    const { useAircraftDemoStore } = await importFresh();
    expect(useAircraftDemoStore.getState().enabled).toBe(true);
  });

  it('falls back to disabled for invalid JSON', async () => {
    localStorage.setItem(STORAGE_KEY, '{not-json');
    const { useAircraftDemoStore } = await importFresh();
    expect(useAircraftDemoStore.getState().enabled).toBe(false);
  });

  it('setEnabled updates state and persists', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useAircraftDemoStore } = await importFresh();

    useAircraftDemoStore.getState().setEnabled(true);
    expect(useAircraftDemoStore.getState().enabled).toBe(true);

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toEqual({ enabled: true });
  });

  it('toggleEnabled flips enabled', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useAircraftDemoStore } = await importFresh();

    expect(useAircraftDemoStore.getState().enabled).toBe(false);
    useAircraftDemoStore.getState().toggleEnabled();
    expect(useAircraftDemoStore.getState().enabled).toBe(true);
  });

  it('useAircraftDemoStore subscribes via useSyncExternalStore', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useAircraftDemoStore } = await importFresh();

    function EnabledLabel() {
      const enabled = useAircraftDemoStore((state) => state.enabled);
      return createElement('div', { 'data-testid': 'enabled' }, String(enabled));
    }

    render(createElement(EnabledLabel));
    expect(screen.getByTestId('enabled')).toHaveTextContent('false');

    act(() => {
      useAircraftDemoStore.getState().setEnabled(true);
    });

    expect(screen.getByTestId('enabled')).toHaveTextContent('true');
  });
});

