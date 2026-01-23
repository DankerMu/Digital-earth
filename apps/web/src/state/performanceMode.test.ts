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
    expect(usePerformanceModeStore.getState().voxelCloudQuality).toBe('high');
    expect(usePerformanceModeStore.getState().autoDowngrade).toBe(true);
  });

  it('restores a valid persisted mode', async () => {
    writeStorage({ mode: 'low' });
    const { usePerformanceModeStore } = await importFresh();
    expect(usePerformanceModeStore.getState().mode).toBe('low');
    expect(usePerformanceModeStore.getState().enabled).toBe(true);
    expect(usePerformanceModeStore.getState().voxelCloudQuality).toBe('low');
    expect(usePerformanceModeStore.getState().autoDowngrade).toBe(true);
  });

  it('restores a persisted string mode', async () => {
    writeStorage('low');
    const { usePerformanceModeStore } = await importFresh();
    expect(usePerformanceModeStore.getState().mode).toBe('low');
    expect(usePerformanceModeStore.getState().voxelCloudQuality).toBe('low');
  });

  it('falls back to defaults when persisted JSON is invalid', async () => {
    localStorage.setItem(STORAGE_KEY, '{');
    const { usePerformanceModeStore } = await importFresh();
    expect(usePerformanceModeStore.getState().mode).toBe('high');
    expect(usePerformanceModeStore.getState().voxelCloudQuality).toBe('high');
  });

  it('falls back to defaults when persisted state is not an object', async () => {
    writeStorage(123);
    const { usePerformanceModeStore } = await importFresh();
    expect(usePerformanceModeStore.getState().mode).toBe('high');
    expect(usePerformanceModeStore.getState().voxelCloudQuality).toBe('high');
  });

  it('migrates legacy enabled:true storage to low mode', async () => {
    writeStorage({ enabled: true });
    const { usePerformanceModeStore } = await importFresh();
    expect(usePerformanceModeStore.getState().mode).toBe('low');
    expect(usePerformanceModeStore.getState().voxelCloudQuality).toBe('low');
  });

  it('restores voxelCloudQuality and autoDowngrade when persisted', async () => {
    writeStorage({ mode: 'high', voxelCloudQuality: 'medium', autoDowngrade: false });
    const { usePerformanceModeStore } = await importFresh();
    expect(usePerformanceModeStore.getState().mode).toBe('high');
    expect(usePerformanceModeStore.getState().voxelCloudQuality).toBe('medium');
    expect(usePerformanceModeStore.getState().autoDowngrade).toBe(false);
  });

  it('falls back to a mode-based quality when persisted voxelCloudQuality is invalid', async () => {
    writeStorage({ mode: 'low', voxelCloudQuality: 'ultra' });
    const { usePerformanceModeStore } = await importFresh();
    expect(usePerformanceModeStore.getState().mode).toBe('low');
    expect(usePerformanceModeStore.getState().voxelCloudQuality).toBe('low');
  });

  it('migrates legacy enabled:false storage to high mode', async () => {
    writeStorage({ enabled: false });
    const { usePerformanceModeStore } = await importFresh();
    expect(usePerformanceModeStore.getState().mode).toBe('high');
    expect(usePerformanceModeStore.getState().enabled).toBe(false);
    expect(usePerformanceModeStore.getState().voxelCloudQuality).toBe('high');
  });

  it('setMode updates state and persists', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { usePerformanceModeStore } = await importFresh();

    usePerformanceModeStore.getState().setMode('low');
    expect(usePerformanceModeStore.getState().mode).toBe('low');

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toEqual({ mode: 'low', voxelCloudQuality: 'high', autoDowngrade: true });
  });

  it('setMode is a no-op when the value is unchanged', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { usePerformanceModeStore } = await importFresh();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();

    usePerformanceModeStore.getState().setMode('high');
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('setEnabled updates mode and persists', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { usePerformanceModeStore } = await importFresh();

    usePerformanceModeStore.getState().setEnabled(true);
    expect(usePerformanceModeStore.getState().mode).toBe('low');

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toEqual({ mode: 'low', voxelCloudQuality: 'high', autoDowngrade: true });
  });

  it('setVoxelCloudQuality is a no-op when the value is unchanged', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { usePerformanceModeStore } = await importFresh();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();

    usePerformanceModeStore.getState().setVoxelCloudQuality('high');
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('setAutoDowngrade is a no-op when the value is unchanged', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { usePerformanceModeStore } = await importFresh();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();

    usePerformanceModeStore.getState().setAutoDowngrade(true);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('handles localStorage write failures without throwing', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });

    const { usePerformanceModeStore } = await importFresh();
    expect(() => usePerformanceModeStore.getState().setMode('low')).not.toThrow();
    expect(usePerformanceModeStore.getState().mode).toBe('low');

    setItemSpy.mockRestore();
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

  it('setVoxelCloudQuality updates state and persists', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { usePerformanceModeStore } = await importFresh();

    usePerformanceModeStore.getState().setVoxelCloudQuality('medium');
    expect(usePerformanceModeStore.getState().voxelCloudQuality).toBe('medium');

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toEqual({ mode: 'high', voxelCloudQuality: 'medium', autoDowngrade: true });
  });

  it('setAutoDowngrade updates state and persists', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { usePerformanceModeStore } = await importFresh();

    usePerformanceModeStore.getState().setAutoDowngrade(false);
    expect(usePerformanceModeStore.getState().autoDowngrade).toBe(false);

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toEqual({ mode: 'high', voxelCloudQuality: 'high', autoDowngrade: false });
  });

  it('setState can update voxel cloud flags', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { usePerformanceModeStore } = await importFresh();

    usePerformanceModeStore.setState({ voxelCloudQuality: 'low', autoDowngrade: false });
    expect(usePerformanceModeStore.getState().voxelCloudQuality).toBe('low');
    expect(usePerformanceModeStore.getState().autoDowngrade).toBe(false);
  });

  it('setState can update mode, quality, and autoDowngrade together', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { usePerformanceModeStore } = await importFresh();

    usePerformanceModeStore.setState({ mode: 'low', voxelCloudQuality: 'medium', autoDowngrade: false });
    expect(usePerformanceModeStore.getState().mode).toBe('low');
    expect(usePerformanceModeStore.getState().voxelCloudQuality).toBe('medium');
    expect(usePerformanceModeStore.getState().autoDowngrade).toBe(false);
  });

  it('setState prefers mode when mode and enabled are both provided', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { usePerformanceModeStore } = await importFresh();

    usePerformanceModeStore.setState({ mode: 'high', enabled: true });
    expect(usePerformanceModeStore.getState().mode).toBe('high');
  });

  it('setState can update mode via enabled when mode is absent', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { usePerformanceModeStore } = await importFresh();

    usePerformanceModeStore.setState({ enabled: true });
    expect(usePerformanceModeStore.getState().mode).toBe('low');
  });

  it('setState ignores invalid voxelCloudQuality values', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { usePerformanceModeStore } = await importFresh();

    usePerformanceModeStore.setState({ voxelCloudQuality: 'ultra' as never });
    expect(usePerformanceModeStore.getState().voxelCloudQuality).toBe('high');
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
