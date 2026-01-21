import { act, render, screen } from '@testing-library/react';
import { createElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

const STORAGE_KEY = 'digital-earth.viewMode';

async function importFresh() {
  vi.resetModules();
  return await import('./viewMode');
}

function writeStorage(value: unknown) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
}

describe('viewMode store', () => {
  it('defaults to global when localStorage is empty', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { DEFAULT_VIEW_MODE_ID, useViewModeStore } = await importFresh();

    const state = useViewModeStore.getState();
    expect(state.viewModeId).toBe(DEFAULT_VIEW_MODE_ID);
    expect(state.route).toEqual({ viewModeId: 'global' });
    expect(state.history).toEqual([]);
    expect(state.canGoBack).toBe(false);
    expect(state.saved).toEqual({});
    expect(state.transition).toBeNull();
  });

  it('restores a valid persisted route, history, and saved state', async () => {
    writeStorage({
      route: { viewModeId: 'event', productId: 'snow-risk' },
      history: [
        { viewModeId: 'global' },
        { viewModeId: 'local', lat: 10, lon: 20 },
      ],
      saved: {
        local: { lat: 1, lon: 2 },
        event: { productId: 'previous-event' },
        layerGlobal: { layerId: 'wind' },
      },
    });

    const { useViewModeStore } = await importFresh();
    const state = useViewModeStore.getState();

    expect(state.route).toEqual({ viewModeId: 'event', productId: 'snow-risk' });
    expect(state.history).toEqual([
      { viewModeId: 'global' },
      { viewModeId: 'local', lat: 10, lon: 20 },
    ]);
    expect(state.saved).toEqual({
      local: { lat: 1, lon: 2 },
      event: { productId: 'previous-event' },
      layerGlobal: { layerId: 'wind' },
    });
    expect(state.canGoBack).toBe(true);
  });

  it('falls back to global when persisted JSON is invalid', async () => {
    localStorage.setItem(STORAGE_KEY, '{');
    const { useViewModeStore } = await importFresh();
    expect(useViewModeStore.getState().route).toEqual({ viewModeId: 'global' });
  });

  it('falls back to global when persisted JSON is not an object', async () => {
    localStorage.setItem(STORAGE_KEY, 'null');
    const { useViewModeStore } = await importFresh();
    expect(useViewModeStore.getState().route).toEqual({ viewModeId: 'global' });
  });

  it('treats non-array history and non-object saved as empty', async () => {
    writeStorage({
      route: { viewModeId: 'layerGlobal', layerId: 'wind' },
      history: 'nope',
      saved: null,
    });

    const { useViewModeStore } = await importFresh();
    expect(useViewModeStore.getState().route).toEqual({ viewModeId: 'layerGlobal', layerId: 'wind' });
    expect(useViewModeStore.getState().history).toEqual([]);
    expect(useViewModeStore.getState().saved).toEqual({});
  });

  it('filters invalid persisted shapes', async () => {
    writeStorage({
      route: { viewModeId: 'local', lat: 'nope', lon: 0 },
      history: [
        { viewModeId: 'global' },
        { viewModeId: 'event', productId: '' },
        { viewModeId: 'local', lat: 30, lon: 40 },
      ],
      saved: {
        local: { lat: 91, lon: 0 },
        event: { productId: 'ok' },
        layerGlobal: { layerId: '' },
      },
    });

    const { useViewModeStore } = await importFresh();
    const state = useViewModeStore.getState();

    expect(state.route).toEqual({ viewModeId: 'global' });
    expect(state.history).toEqual([
      { viewModeId: 'global' },
      { viewModeId: 'local', lat: 30, lon: 40 },
    ]);
    expect(state.saved).toEqual({ event: { productId: 'ok' } });
  });

  it('navigates forward, records history, and persists', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useViewModeStore } = await importFresh();

    useViewModeStore.getState().enterLocal({ lat: 30, lon: 40 });

    const state = useViewModeStore.getState();
    expect(state.route).toEqual({ viewModeId: 'local', lat: 30, lon: 40 });
    expect(state.history).toEqual([{ viewModeId: 'global' }]);
    expect(state.transition?.kind).toBe('forward');
    expect(state.transition?.from).toEqual({ viewModeId: 'global' });
    expect(state.transition?.to).toEqual({ viewModeId: 'local', lat: 30, lon: 40 });
    expect(state.canGoBack).toBe(true);

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toMatchObject({
      route: { viewModeId: 'local', lat: 30, lon: 40 },
      history: [{ viewModeId: 'global' }],
    });
  });

  it('saves per-mode state when leaving a mode and supports goBack()', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useViewModeStore } = await importFresh();

    useViewModeStore.getState().enterLocal({ lat: 12.5, lon: 99.1 });
    useViewModeStore.getState().enterEvent({ productId: '  snow  ' });

    expect(useViewModeStore.getState().route).toEqual({
      viewModeId: 'event',
      productId: 'snow',
    });
    expect(useViewModeStore.getState().saved).toEqual({
      local: { lat: 12.5, lon: 99.1 },
    });

    const backed = useViewModeStore.getState().goBack();
    expect(backed).toBe(true);
    expect(useViewModeStore.getState().route).toEqual({
      viewModeId: 'local',
      lat: 12.5,
      lon: 99.1,
    });
    expect(useViewModeStore.getState().transition?.kind).toBe('back');
    expect(useViewModeStore.getState().saved).toEqual({
      local: { lat: 12.5, lon: 99.1 },
      event: { productId: 'snow' },
    });
  });

  it('saves layerGlobal state when leaving the mode', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useViewModeStore } = await importFresh();

    useViewModeStore.getState().enterLayerGlobal({ layerId: 'wind' });
    useViewModeStore.getState().enterGlobal();

    expect(useViewModeStore.getState().saved).toEqual({
      layerGlobal: { layerId: 'wind' },
    });
  });

  it('returns false when goBack() is called with no history', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useViewModeStore } = await importFresh();

    expect(useViewModeStore.getState().goBack()).toBe(false);
    expect(useViewModeStore.getState().route).toEqual({ viewModeId: 'global' });
  });

  it('does not change state when navigating to the same route', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useViewModeStore } = await importFresh();

    useViewModeStore.getState().enterGlobal();

    expect(useViewModeStore.getState().route).toEqual({ viewModeId: 'global' });
    expect(useViewModeStore.getState().history).toEqual([]);
    expect(useViewModeStore.getState().transition).toBeNull();
  });

  it('treats repeat navigation to the same event/layerGlobal route as a no-op', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useViewModeStore } = await importFresh();

    useViewModeStore.getState().enterEvent({ productId: 'risk' });
    const historyAfterFirst = useViewModeStore.getState().history;
    const transitionAfterFirst = useViewModeStore.getState().transition;

    useViewModeStore.getState().enterEvent({ productId: 'risk' });
    expect(useViewModeStore.getState().history).toBe(historyAfterFirst);
    expect(useViewModeStore.getState().transition).toBe(transitionAfterFirst);

    useViewModeStore.getState().enterLayerGlobal({ layerId: 'wind' });
    const historyAfterLayer = useViewModeStore.getState().history;
    const transitionAfterLayer = useViewModeStore.getState().transition;

    useViewModeStore.getState().enterLayerGlobal({ layerId: 'wind' });
    expect(useViewModeStore.getState().history).toBe(historyAfterLayer);
    expect(useViewModeStore.getState().transition).toBe(transitionAfterLayer);
  });

  it('ignores invalid inputs', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useViewModeStore } = await importFresh();

    useViewModeStore.getState().enterLocal({ lat: Number.NaN, lon: 0 });
    useViewModeStore.getState().enterLocal({ lat: 100, lon: 0 });
    useViewModeStore.getState().enterEvent({ productId: '   ' });
    useViewModeStore.getState().enterLayerGlobal({ layerId: '   ' });

    expect(useViewModeStore.getState().route).toEqual({ viewModeId: 'global' });
    expect(useViewModeStore.getState().history).toEqual([]);
  });

  it('clearHistory is a no-op when already empty', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useViewModeStore } = await importFresh();

    useViewModeStore.getState().clearHistory();
    expect(useViewModeStore.getState().history).toEqual([]);
    expect(useViewModeStore.getState().transition).toBeNull();
  });

  it('replaceRoute updates the route without pushing history', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useViewModeStore } = await importFresh();

    useViewModeStore.getState().enterLocal({ lat: 10, lon: 20 });
    expect(useViewModeStore.getState().history).toEqual([{ viewModeId: 'global' }]);

    useViewModeStore.getState().replaceRoute({ viewModeId: 'local', lat: 11, lon: 22 });
    expect(useViewModeStore.getState().route).toEqual({
      viewModeId: 'local',
      lat: 11,
      lon: 22,
    });
    expect(useViewModeStore.getState().history).toEqual([{ viewModeId: 'global' }]);
    expect(useViewModeStore.getState().transition?.kind).toBe('replace');
  });

  it('clearHistory removes history entries and persists', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useViewModeStore } = await importFresh();

    useViewModeStore.getState().enterLayerGlobal({ layerId: 'wind' });
    expect(useViewModeStore.getState().history.length).toBe(1);

    useViewModeStore.getState().clearHistory();
    expect(useViewModeStore.getState().history).toEqual([]);
    expect(useViewModeStore.getState().canGoBack).toBe(false);

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toMatchObject({
      route: { viewModeId: 'layerGlobal', layerId: 'wind' },
      history: [],
    });
  });

  it('setState short-circuit comparisons cover all saved branches', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useViewModeStore } = await importFresh();

    useViewModeStore.setState({ saved: { event: { productId: 'storm' } } });
    expect(useViewModeStore.getState().saved).toEqual({ event: { productId: 'storm' } });

    useViewModeStore.setState({ saved: {} });
    expect(useViewModeStore.getState().saved).toEqual({});

    useViewModeStore.setState({ saved: { layerGlobal: { layerId: 'wind' } } });
    expect(useViewModeStore.getState().saved).toEqual({ layerGlobal: { layerId: 'wind' } });
  });

  it('setState validates and persists partial updates', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useViewModeStore } = await importFresh();

    useViewModeStore.setState({
      route: { viewModeId: 'event', productId: 'storm' },
      history: [{ viewModeId: 'global' }, { viewModeId: 'event', productId: '' }],
      saved: {
        local: { lat: 0, lon: 0 },
        event: { productId: 'storm' },
        layerGlobal: { layerId: 'clouds' },
      },
    });

    expect(useViewModeStore.getState().route).toEqual({
      viewModeId: 'event',
      productId: 'storm',
    });
    expect(useViewModeStore.getState().history).toEqual([{ viewModeId: 'global' }]);
    expect(useViewModeStore.getState().saved).toEqual({
      local: { lat: 0, lon: 0 },
      event: { productId: 'storm' },
      layerGlobal: { layerId: 'clouds' },
    });

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toMatchObject({
      route: { viewModeId: 'event', productId: 'storm' },
      history: [{ viewModeId: 'global' }],
    });
  });

  it('setState does nothing when provided an empty patch', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useViewModeStore } = await importFresh();

    useViewModeStore.setState({});
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('useViewModeStore subscribes via useSyncExternalStore', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useViewModeStore } = await importFresh();

    function ViewModeLabel() {
      const viewModeId = useViewModeStore((state) => state.viewModeId);
      return createElement('div', { 'data-testid': 'mode' }, viewModeId);
    }

    render(createElement(ViewModeLabel));
    expect(screen.getByTestId('mode')).toHaveTextContent('global');

    act(() => {
      useViewModeStore.getState().enterEvent({ productId: 'risk' });
    });

    expect(screen.getByTestId('mode')).toHaveTextContent('event');
  });

  it('handles localStorage read/write failures without throwing', async () => {
    localStorage.removeItem(STORAGE_KEY);

    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });

    const { useViewModeStore } = await importFresh();
    expect(useViewModeStore.getState().route).toEqual({ viewModeId: 'global' });
    getItem.mockRestore();

    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });

    expect(() => {
      useViewModeStore.getState().enterEvent({ productId: 'risk' });
    }).not.toThrow();
    expect(useViewModeStore.getState().route).toEqual({ viewModeId: 'event', productId: 'risk' });
    setItem.mockRestore();
  });
});

describe('isViewModeId', () => {
  it('accepts only the supported ids', async () => {
    const { isViewModeId } = await importFresh();

    expect(isViewModeId('global')).toBe(true);
    expect(isViewModeId('local')).toBe(true);
    expect(isViewModeId('event')).toBe(true);
    expect(isViewModeId('layerGlobal')).toBe(true);

    expect(isViewModeId('nope')).toBe(false);
    expect(isViewModeId(123)).toBe(false);
    expect(isViewModeId(null)).toBe(false);
  });
});
