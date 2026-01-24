import { describe, expect, it, vi } from 'vitest';

const STORAGE_KEY = 'digital-earth.layoutPanels';

async function importFresh() {
  vi.resetModules();
  return await import('./layoutPanels');
}

function writeStorage(value: unknown) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
}

describe('layoutPanels store', () => {
  it('defaults to expanded panels when localStorage is empty', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useLayoutPanelsStore } = await importFresh();

    expect(useLayoutPanelsStore.getState().timelineCollapsed).toBe(false);
    expect(useLayoutPanelsStore.getState().layerTreeCollapsed).toBe(false);
    expect(useLayoutPanelsStore.getState().infoPanelCollapsed).toBe(true);
    expect(useLayoutPanelsStore.getState().legendCollapsed).toBe(false);
  });

  it('restores persisted panel states', async () => {
    writeStorage({
      timelineCollapsed: true,
      layerTreeCollapsed: false,
      infoPanelCollapsed: true,
      legendCollapsed: false,
    });

    const { useLayoutPanelsStore } = await importFresh();
    const state = useLayoutPanelsStore.getState();

    expect(state.timelineCollapsed).toBe(true);
    expect(state.layerTreeCollapsed).toBe(false);
    expect(state.infoPanelCollapsed).toBe(true);
    expect(state.legendCollapsed).toBe(false);
  });

  it('falls back when persisted JSON is invalid', async () => {
    localStorage.setItem(STORAGE_KEY, '{');
    const { useLayoutPanelsStore } = await importFresh();
    expect(useLayoutPanelsStore.getState().timelineCollapsed).toBe(false);
  });

  it('falls back when persisted JSON is not an object', async () => {
    localStorage.setItem(STORAGE_KEY, 'null');
    const { useLayoutPanelsStore } = await importFresh();
    expect(useLayoutPanelsStore.getState().layerTreeCollapsed).toBe(false);
  });

  it('persists state changes', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useLayoutPanelsStore } = await importFresh();

    useLayoutPanelsStore.getState().toggleLayerTreeCollapsed();
    expect(useLayoutPanelsStore.getState().layerTreeCollapsed).toBe(true);

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toEqual({
      timelineCollapsed: false,
      layerTreeCollapsed: true,
      infoPanelCollapsed: true,
      legendCollapsed: false,
    });
  });

  it('supports setters and setState', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useLayoutPanelsStore } = await importFresh();

    useLayoutPanelsStore.getState().setTimelineCollapsed(true);
    useLayoutPanelsStore.getState().setLayerTreeCollapsed(true);
    useLayoutPanelsStore.getState().setInfoPanelCollapsed(true);
    useLayoutPanelsStore.getState().setLegendCollapsed(true);

    expect(useLayoutPanelsStore.getState().timelineCollapsed).toBe(true);
    expect(useLayoutPanelsStore.getState().layerTreeCollapsed).toBe(true);
    expect(useLayoutPanelsStore.getState().infoPanelCollapsed).toBe(true);
    expect(useLayoutPanelsStore.getState().legendCollapsed).toBe(true);

    useLayoutPanelsStore.setState({ legendCollapsed: false });
    expect(useLayoutPanelsStore.getState().legendCollapsed).toBe(false);

    useLayoutPanelsStore.getState().toggleTimelineCollapsed();
    expect(useLayoutPanelsStore.getState().timelineCollapsed).toBe(false);
  });
});
