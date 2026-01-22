import { act, render, screen } from '@testing-library/react';
import { createElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

const STORAGE_KEY = 'digital-earth.performanceMode';

async function importFresh() {
  vi.resetModules();
  return await import('./performanceMode');
}

function writeStorage(value: unknown) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
}

describe('performanceMode store', () => {
  it('defaults to high when localStorage is empty', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { usePerformanceModeStore } = await importFresh();
    expect(usePerformanceModeStore.getState().mode).toBe('high');
    expect(usePerformanceModeStore.getState().enabled).toBe(false);
  });

  it('restores a valid persisted mode', async () => {
    writeStorage({ mode: 'low' });
    const { usePerformanceModeStore } = await importFresh();
    expect(usePerformanceModeStore.getState().mode).toBe('low');
    expect(usePerformanceModeStore.getState().enabled).toBe(true);
  });

  it('migrates legacy enabled:true storage to low mode', async () => {
    writeStorage({ enabled: true });
    const { usePerformanceModeStore } = await importFresh();
    expect(usePerformanceModeStore.getState().mode).toBe('low');
  });

  it('setMode updates state and persists', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { usePerformanceModeStore } = await importFresh();

    usePerformanceModeStore.getState().setMode('low');
    expect(usePerformanceModeStore.getState().mode).toBe('low');

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toEqual({ mode: 'low' });
  });

  it('setEnabled updates mode and persists', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { usePerformanceModeStore } = await importFresh();

    usePerformanceModeStore.getState().setEnabled(true);
    expect(usePerformanceModeStore.getState().mode).toBe('low');

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toEqual({ mode: 'low' });
  });

  it('toggleMode switches between high and low', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { usePerformanceModeStore } = await importFresh();

    expect(usePerformanceModeStore.getState().mode).toBe('high');
    usePerformanceModeStore.getState().toggleMode();
    expect(usePerformanceModeStore.getState().mode).toBe('low');
    usePerformanceModeStore.getState().toggleMode();
    expect(usePerformanceModeStore.getState().mode).toBe('high');
  });

  it('usePerformanceModeStore subscribes via useSyncExternalStore', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { usePerformanceModeStore } = await importFresh();

    function ModeLabel() {
      const mode = usePerformanceModeStore((state) => state.mode);
      return createElement('div', { 'data-testid': 'mode' }, mode);
    }

    render(createElement(ModeLabel));
    expect(screen.getByTestId('mode')).toHaveTextContent('high');

    act(() => {
      usePerformanceModeStore.getState().setMode('low');
    });

    expect(screen.getByTestId('mode')).toHaveTextContent('low');
  });
});

