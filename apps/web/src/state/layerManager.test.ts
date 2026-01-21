import { act, render, screen } from '@testing-library/react';
import { createElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

const STORAGE_KEY = 'digital-earth.layers';

async function importFresh() {
  vi.resetModules();
  return await import('./layerManager');
}

function writeStorage(value: unknown) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
}

describe('layerManager store', () => {
  it('defaults to an empty registry when localStorage is empty', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useLayerManagerStore } = await importFresh();

    const state = useLayerManagerStore.getState();
    expect(state.layers).toEqual([]);
    expect(state.getVisibleLayers()).toEqual([]);
  });

  it('restores valid persisted layers and enforces per-type visibility exclusivity', async () => {
    writeStorage({
      layers: [
        {
          id: 'cloud-low',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.5,
          visible: true,
          zIndex: 5,
        },
        {
          id: 'cloud-high',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.8,
          visible: true,
          zIndex: 10,
        },
        {
          id: 'wind-850',
          type: 'wind',
          variable: 'wind',
          level: 850,
          opacity: 1,
          visible: true,
          zIndex: 7,
        },
      ],
    });

    const { useLayerManagerStore } = await importFresh();
    const state = useLayerManagerStore.getState();

    expect(state.layers.map((layer) => layer.id)).toEqual([
      'cloud-low',
      'wind-850',
      'cloud-high',
    ]);

    const visible = state.getVisibleLayers();
    expect(visible.map((layer) => layer.id)).toEqual(['wind-850', 'cloud-high']);
    expect(state.layers.find((layer) => layer.id === 'cloud-low')?.visible).toBe(false);
  });

  it('restores layers from an array payload, ignores invalid entries, and sorts ties by id', async () => {
    localStorage.removeItem(STORAGE_KEY);

    writeStorage([
      {
        id: 'b',
        type: 'cloud',
        variable: 'tcc',
        opacity: Number.NaN,
        visible: true,
        zIndex: 0,
      },
      {
        id: 'a',
        type: 'cloud',
        variable: 'tcc',
        opacity: 0.5,
        visible: true,
        zIndex: 0,
      },
      {
        id: 'hidden-wind',
        type: 'wind',
        variable: 'wind',
        opacity: 1,
        visible: false,
        zIndex: 1,
      },
      null,
      { id: '', type: 'temperature', variable: 't2m', opacity: 1, visible: true, zIndex: 2 },
    ]);

    const { useLayerManagerStore } = await importFresh();
    const state = useLayerManagerStore.getState();

    expect(state.layers.map((layer) => layer.id)).toEqual(['a', 'b', 'hidden-wind']);
    expect(state.getVisibleLayers().map((layer) => layer.id)).toEqual(['b']);
    expect(state.layers.find((layer) => layer.id === 'b')?.opacity).toBe(1);
  });

  it('falls back to an empty registry when persisted JSON is invalid', async () => {
    localStorage.setItem(STORAGE_KEY, '{');
    const { useLayerManagerStore } = await importFresh();
    expect(useLayerManagerStore.getState().layers).toEqual([]);
  });

  it('treats non-layer payloads as empty', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(123));
    expect((await importFresh()).useLayerManagerStore.getState().layers).toEqual([]);

    writeStorage({ layers: 'nope' });
    expect((await importFresh()).useLayerManagerStore.getState().layers).toEqual([]);
  });

  it('registerLayer inserts layers, sorts by zIndex, and persists', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useLayerManagerStore } = await importFresh();

    useLayerManagerStore.getState().registerLayer({
      id: 'cloud',
      type: 'cloud',
      variable: 'tcc',
      opacity: 0.4,
      visible: true,
      zIndex: 10,
    });

    useLayerManagerStore.getState().registerLayer({
      id: 'temperature',
      type: 'temperature',
      variable: 't2m',
      opacity: 1,
      visible: true,
      zIndex: 5,
    });

    expect(useLayerManagerStore.getState().layers.map((layer) => layer.id)).toEqual([
      'temperature',
      'cloud',
    ]);

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toMatchObject({
      layers: [
        expect.objectContaining({ id: 'temperature' }),
        expect.objectContaining({ id: 'cloud' }),
      ],
    });
  });

  it('registerLayer validates inputs, upserts, and short-circuits equal updates', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useLayerManagerStore } = await importFresh();

    const setItem = vi.spyOn(Storage.prototype, 'setItem');

    expect(() => {
      useLayerManagerStore.getState().registerLayer(123 as never);
      useLayerManagerStore.getState().registerLayer({
        id: '   ',
        type: 'cloud',
        variable: 'tcc',
        opacity: 1,
        visible: true,
        zIndex: 0,
      } as never);
    }).not.toThrow();

    useLayerManagerStore.getState().registerLayer({
      id: ' cloud ',
      type: 'cloud',
      variable: ' tcc ',
      opacity: Number.NaN,
      visible: true,
      zIndex: Number.NaN,
    } as never);

    expect(useLayerManagerStore.getState().layers).toEqual([
      {
        id: 'cloud',
        type: 'cloud',
        variable: 'tcc',
        opacity: 1,
        visible: true,
        zIndex: 0,
      },
    ]);

    setItem.mockClear();

    useLayerManagerStore.getState().registerLayer({
      id: 'cloud',
      type: 'cloud',
      variable: 'tcc',
      opacity: 1,
      visible: true,
      zIndex: 0,
    });

    expect(setItem).not.toHaveBeenCalled();

    useLayerManagerStore.getState().registerLayer({
      id: 'cloud',
      type: 'cloud',
      variable: 'tcc',
      opacity: 0.5,
      visible: true,
      zIndex: 0,
    });

    expect(useLayerManagerStore.getState().layers.find((layer) => layer.id === 'cloud')?.opacity).toBe(0.5);
    expect(setItem).toHaveBeenCalledTimes(1);

    setItem.mockRestore();
  });

  it('enforces mutual exclusivity when registering multiple visible layers of the same type', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useLayerManagerStore } = await importFresh();

    useLayerManagerStore.getState().registerLayer({
      id: 'cloud-a',
      type: 'cloud',
      variable: 'tcc',
      opacity: 0.5,
      visible: true,
      zIndex: 0,
    });

    useLayerManagerStore.getState().registerLayer({
      id: 'cloud-b',
      type: 'cloud',
      variable: 'tcc',
      opacity: 0.7,
      visible: true,
      zIndex: 1,
    });

    const state = useLayerManagerStore.getState();
    expect(state.getVisibleLayers().map((layer) => layer.id)).toEqual(['cloud-b']);
    expect(state.layers.find((layer) => layer.id === 'cloud-a')?.visible).toBe(false);
    expect(state.layers.find((layer) => layer.id === 'cloud-b')?.visible).toBe(true);
  });

  it('unregisterLayer removes layers and is a no-op for missing ids', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useLayerManagerStore } = await importFresh();

    useLayerManagerStore.getState().registerLayer({
      id: 'cloud',
      type: 'cloud',
      variable: 'tcc',
      opacity: 1,
      visible: true,
      zIndex: 0,
    });

    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    setItem.mockClear();

    useLayerManagerStore.getState().unregisterLayer('   ');
    useLayerManagerStore.getState().unregisterLayer('missing');
    expect(useLayerManagerStore.getState().layers.length).toBe(1);
    expect(setItem).not.toHaveBeenCalled();

    useLayerManagerStore.getState().unregisterLayer('cloud');
    expect(useLayerManagerStore.getState().layers).toEqual([]);
    expect(setItem).toHaveBeenCalledTimes(1);

    setItem.mockRestore();
  });

  it('setLayerVisible makes the target layer visible and hides same-type siblings', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useLayerManagerStore } = await importFresh();

    useLayerManagerStore.getState().registerLayer({
      id: 'cloud-a',
      type: 'cloud',
      variable: 'tcc',
      opacity: 0.5,
      visible: true,
      zIndex: 0,
    });

    useLayerManagerStore.getState().registerLayer({
      id: 'cloud-b',
      type: 'cloud',
      variable: 'tcc',
      opacity: 0.7,
      visible: false,
      zIndex: 1,
    });

    useLayerManagerStore.getState().setLayerVisible('cloud-b', true);

    const state = useLayerManagerStore.getState();
    expect(state.getVisibleLayers().map((layer) => layer.id)).toEqual(['cloud-b']);
    expect(state.layers.find((layer) => layer.id === 'cloud-a')?.visible).toBe(false);
  });

  it('updateLayer supports partial updates, including clearing level', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useLayerManagerStore } = await importFresh();

    useLayerManagerStore.getState().registerLayer({
      id: 'wind-850',
      type: 'wind',
      variable: 'wind',
      level: 850,
      threshold: 2,
      opacity: 1,
      visible: true,
      zIndex: 0,
    });

    useLayerManagerStore.getState().updateLayer('wind-850', {
      opacity: 0.25,
      zIndex: 5,
      level: undefined,
      threshold: undefined,
    });

    const updated = useLayerManagerStore.getState().layers.find((layer) => layer.id === 'wind-850');
    expect(updated).toMatchObject({
      id: 'wind-850',
      opacity: 0.25,
      zIndex: 5,
      visible: true,
    });
    expect(updated).not.toHaveProperty('level');
    expect(updated).not.toHaveProperty('threshold');
  });

  it('updateLayer supports type/variable/level updates and ignores invalid patches', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useLayerManagerStore } = await importFresh();

    useLayerManagerStore.getState().registerLayer({
      id: 'cloud-a',
      type: 'cloud',
      variable: 'tcc',
      opacity: 1,
      visible: true,
      zIndex: 0,
    });

    useLayerManagerStore.getState().registerLayer({
      id: 'precip',
      type: 'precipitation',
      variable: 'tp',
      opacity: 1,
      visible: true,
      zIndex: 1,
    });

    useLayerManagerStore.getState().updateLayer('precip', { type: 'cloud' });
    expect(useLayerManagerStore.getState().layers.find((layer) => layer.id === 'precip')?.type).toBe('cloud');
    expect(useLayerManagerStore.getState().getVisibleLayers().map((layer) => layer.id)).toEqual(['precip']);

    useLayerManagerStore.getState().updateLayer('precip', { variable: '  newVar  ' });
    expect(useLayerManagerStore.getState().layers.find((layer) => layer.id === 'precip')?.variable).toBe('newVar');

    useLayerManagerStore.getState().updateLayer('precip', { level: 850 });
    expect(useLayerManagerStore.getState().layers.find((layer) => layer.id === 'precip')?.level).toBe(850);

    useLayerManagerStore.getState().updateLayer('precip', { type: 'nope' as never });
    useLayerManagerStore.getState().updateLayer('precip', { variable: '   ' });
    expect(useLayerManagerStore.getState().layers.find((layer) => layer.id === 'precip')?.variable).toBe('newVar');

    useLayerManagerStore.getState().updateLayer('   ', { opacity: 0 });
    useLayerManagerStore.getState().updateLayer('missing', { opacity: 0 });
    expect(useLayerManagerStore.getState().layers.map((layer) => layer.id)).toEqual(['cloud-a', 'precip']);
  });

  it('updateLayer is a no-op when the patch does not change anything', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useLayerManagerStore } = await importFresh();

    useLayerManagerStore.getState().registerLayer({
      id: 'cloud',
      type: 'cloud',
      variable: 'tcc',
      opacity: 1,
      visible: true,
      zIndex: 0,
    });

    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    setItem.mockClear();

    useLayerManagerStore.getState().updateLayer('cloud', { type: 'cloud' });
    expect(setItem).not.toHaveBeenCalled();

    setItem.mockRestore();
  });

  it('setLayerOpacity clamps to [0, 1]', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useLayerManagerStore } = await importFresh();

    useLayerManagerStore.getState().registerLayer({
      id: 'temperature',
      type: 'temperature',
      variable: 't2m',
      opacity: 1,
      visible: true,
      zIndex: 0,
    });

    useLayerManagerStore.getState().setLayerOpacity('temperature', -1);
    expect(useLayerManagerStore.getState().layers.find((layer) => layer.id === 'temperature')?.opacity).toBe(0);

    useLayerManagerStore.getState().setLayerOpacity('temperature', 2);
    expect(useLayerManagerStore.getState().layers.find((layer) => layer.id === 'temperature')?.opacity).toBe(1);
  });

  it('setState validates and persists layer lists', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useLayerManagerStore } = await importFresh();

    const setItem = vi.spyOn(Storage.prototype, 'setItem');

    useLayerManagerStore.setState({});
    expect(setItem).not.toHaveBeenCalled();

    useLayerManagerStore.setState({
      layers: [
        {
          id: 'cloud-a',
          type: 'cloud',
          variable: 'tcc',
          opacity: 1,
          visible: true,
          zIndex: 1,
        },
        {
          id: 'cloud-a',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.5,
          visible: false,
          zIndex: 0,
        },
        {
          id: 'wind',
          type: 'wind',
          variable: 'wind',
          opacity: 1,
          visible: true,
          zIndex: 2,
        },
        {
          id: 'wind2',
          type: 'wind',
          variable: 'wind',
          opacity: 1,
          visible: true,
          zIndex: 3,
        },
        { id: 'bad', type: 'nope', variable: 'x', opacity: 1, visible: true, zIndex: 4 },
      ] as never,
    });

    expect(useLayerManagerStore.getState().layers.map((layer) => layer.id)).toEqual([
      'cloud-a',
      'wind',
      'wind2',
    ]);
    expect(useLayerManagerStore.getState().getVisibleLayers().map((layer) => layer.id)).toEqual(['wind2']);
    expect(setItem).toHaveBeenCalledTimes(1);

    setItem.mockClear();
    useLayerManagerStore.setState({ layers: useLayerManagerStore.getState().layers });
    expect(setItem).not.toHaveBeenCalled();

    setItem.mockRestore();
  });

  it('getLayersByType returns matching layers (sorted by zIndex)', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useLayerManagerStore } = await importFresh();

    useLayerManagerStore.getState().registerLayer({
      id: 'cloud',
      type: 'cloud',
      variable: 'tcc',
      opacity: 1,
      visible: false,
      zIndex: 10,
    });

    useLayerManagerStore.getState().registerLayer({
      id: 'cloud-low',
      type: 'cloud',
      variable: 'tcc',
      opacity: 1,
      visible: false,
      zIndex: 0,
    });

    useLayerManagerStore.getState().registerLayer({
      id: 'wind',
      type: 'wind',
      variable: 'wind',
      opacity: 1,
      visible: false,
      zIndex: 5,
    });

    expect(useLayerManagerStore.getState().getLayersByType('cloud').map((layer) => layer.id)).toEqual([
      'cloud-low',
      'cloud',
    ]);
  });

  it('supports batching to persist once for multiple updates', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const setItem = vi.spyOn(Storage.prototype, 'setItem');

    const { useLayerManagerStore } = await importFresh();

    useLayerManagerStore.getState().batch(() => {
      useLayerManagerStore.getState().registerLayer({
        id: 'cloud',
        type: 'cloud',
        variable: 'tcc',
        opacity: 1,
        visible: true,
        zIndex: 0,
      });

      useLayerManagerStore.getState().setLayerOpacity('cloud', 0.5);
    });

    expect(setItem).toHaveBeenCalledTimes(1);
    setItem.mockRestore();
  });

  it('useLayerManagerStore subscribes via useSyncExternalStore', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useLayerManagerStore } = await importFresh();

    function VisibleCount() {
      const count = useLayerManagerStore((state) => state.getVisibleLayers().length);
      return createElement('div', { 'data-testid': 'count' }, String(count));
    }

    render(createElement(VisibleCount));
    expect(screen.getByTestId('count')).toHaveTextContent('0');

    act(() => {
      useLayerManagerStore.getState().registerLayer({
        id: 'temperature',
        type: 'temperature',
        variable: 't2m',
        opacity: 1,
        visible: true,
        zIndex: 0,
      });
    });

    expect(screen.getByTestId('count')).toHaveTextContent('1');
  });

  it('handles localStorage read/write failures without throwing', async () => {
    localStorage.removeItem(STORAGE_KEY);

    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });

    const { useLayerManagerStore } = await importFresh();
    expect(useLayerManagerStore.getState().layers).toEqual([]);
    getItem.mockRestore();

    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });

    expect(() => {
      useLayerManagerStore.getState().registerLayer({
        id: 'cloud',
        type: 'cloud',
        variable: 'tcc',
        opacity: 1,
        visible: true,
        zIndex: 0,
      });
    }).not.toThrow();

    expect(useLayerManagerStore.getState().layers.find((layer) => layer.id === 'cloud')?.visible).toBe(true);
    setItem.mockRestore();
  });
});

describe('isLayerType', () => {
  it('accepts only supported layer types', async () => {
    const { isLayerType } = await importFresh();

    expect(isLayerType('temperature')).toBe(true);
    expect(isLayerType('cloud')).toBe(true);
    expect(isLayerType('precipitation')).toBe(true);
    expect(isLayerType('wind')).toBe(true);

    expect(isLayerType('nope')).toBe(false);
    expect(isLayerType(123)).toBe(false);
    expect(isLayerType(null)).toBe(false);
  });
});
