import { useSyncExternalStore } from 'react';

export type LayoutPanelsState = {
  timelineCollapsed: boolean;
  layerTreeCollapsed: boolean;
  infoPanelCollapsed: boolean;
  legendCollapsed: boolean;
  setTimelineCollapsed: (collapsed: boolean) => void;
  setLayerTreeCollapsed: (collapsed: boolean) => void;
  setInfoPanelCollapsed: (collapsed: boolean) => void;
  setLegendCollapsed: (collapsed: boolean) => void;
  toggleTimelineCollapsed: () => void;
  toggleLayerTreeCollapsed: () => void;
  toggleInfoPanelCollapsed: () => void;
  toggleLegendCollapsed: () => void;
};

const STORAGE_KEY = 'digital-earth.layoutPanels';

type Listener = () => void;

const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) listener();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

type PersistedLayoutPanelsState = {
  timelineCollapsed: boolean;
  layerTreeCollapsed: boolean;
  infoPanelCollapsed: boolean;
  legendCollapsed: boolean;
};

const DEFAULT_PERSISTED: PersistedLayoutPanelsState = {
  timelineCollapsed: false,
  layerTreeCollapsed: false,
  infoPanelCollapsed: false,
  legendCollapsed: false,
};

function safeReadPersisted(): PersistedLayoutPanelsState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_PERSISTED;
    const parsed = JSON.parse(raw) as unknown;
    if (!isRecord(parsed)) return DEFAULT_PERSISTED;

    return {
      timelineCollapsed: parsed.timelineCollapsed === true,
      layerTreeCollapsed: parsed.layerTreeCollapsed === true,
      infoPanelCollapsed: parsed.infoPanelCollapsed === true,
      legendCollapsed: parsed.legendCollapsed === true,
    };
  } catch {
    return DEFAULT_PERSISTED;
  }
}

function safeWritePersisted(next: PersistedLayoutPanelsState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // ignore write failures (e.g., disabled storage)
  }
}

let persisted: PersistedLayoutPanelsState = safeReadPersisted();

function persist() {
  safeWritePersisted(persisted);
}

const setTimelineCollapsed: LayoutPanelsState['setTimelineCollapsed'] = (collapsed) => {
  if (persisted.timelineCollapsed === collapsed) return;
  persisted = { ...persisted, timelineCollapsed: collapsed };
  persist();
  notify();
};

const setLayerTreeCollapsed: LayoutPanelsState['setLayerTreeCollapsed'] = (collapsed) => {
  if (persisted.layerTreeCollapsed === collapsed) return;
  persisted = { ...persisted, layerTreeCollapsed: collapsed };
  persist();
  notify();
};

const setInfoPanelCollapsed: LayoutPanelsState['setInfoPanelCollapsed'] = (collapsed) => {
  if (persisted.infoPanelCollapsed === collapsed) return;
  persisted = { ...persisted, infoPanelCollapsed: collapsed };
  persist();
  notify();
};

const setLegendCollapsed: LayoutPanelsState['setLegendCollapsed'] = (collapsed) => {
  if (persisted.legendCollapsed === collapsed) return;
  persisted = { ...persisted, legendCollapsed: collapsed };
  persist();
  notify();
};

const toggleTimelineCollapsed: LayoutPanelsState['toggleTimelineCollapsed'] = () => {
  setTimelineCollapsed(!persisted.timelineCollapsed);
};

const toggleLayerTreeCollapsed: LayoutPanelsState['toggleLayerTreeCollapsed'] = () => {
  setLayerTreeCollapsed(!persisted.layerTreeCollapsed);
};

const toggleInfoPanelCollapsed: LayoutPanelsState['toggleInfoPanelCollapsed'] = () => {
  setInfoPanelCollapsed(!persisted.infoPanelCollapsed);
};

const toggleLegendCollapsed: LayoutPanelsState['toggleLegendCollapsed'] = () => {
  setLegendCollapsed(!persisted.legendCollapsed);
};

function getState(): LayoutPanelsState {
  return {
    timelineCollapsed: persisted.timelineCollapsed,
    layerTreeCollapsed: persisted.layerTreeCollapsed,
    infoPanelCollapsed: persisted.infoPanelCollapsed,
    legendCollapsed: persisted.legendCollapsed,
    setTimelineCollapsed,
    setLayerTreeCollapsed,
    setInfoPanelCollapsed,
    setLegendCollapsed,
    toggleTimelineCollapsed,
    toggleLayerTreeCollapsed,
    toggleInfoPanelCollapsed,
    toggleLegendCollapsed,
  };
}

function setState(partial: Partial<PersistedLayoutPanelsState>) {
  const next: PersistedLayoutPanelsState = {
    timelineCollapsed:
      typeof partial.timelineCollapsed === 'boolean'
        ? partial.timelineCollapsed
        : persisted.timelineCollapsed,
    layerTreeCollapsed:
      typeof partial.layerTreeCollapsed === 'boolean'
        ? partial.layerTreeCollapsed
        : persisted.layerTreeCollapsed,
    infoPanelCollapsed:
      typeof partial.infoPanelCollapsed === 'boolean'
        ? partial.infoPanelCollapsed
        : persisted.infoPanelCollapsed,
    legendCollapsed:
      typeof partial.legendCollapsed === 'boolean'
        ? partial.legendCollapsed
        : persisted.legendCollapsed,
  };

  const didChange =
    next.timelineCollapsed !== persisted.timelineCollapsed ||
    next.layerTreeCollapsed !== persisted.layerTreeCollapsed ||
    next.infoPanelCollapsed !== persisted.infoPanelCollapsed ||
    next.legendCollapsed !== persisted.legendCollapsed;
  if (!didChange) return;

  persisted = next;
  persist();
  notify();
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

type Selector<T> = (state: LayoutPanelsState) => T;

type StoreHook = {
  <T>(selector: Selector<T>): T;
  getState: typeof getState;
  setState: typeof setState;
};

const useLayoutPanelsStoreImpl = <T>(selector: Selector<T>): T =>
  useSyncExternalStore(
    subscribe,
    () => selector(getState()),
    () => selector(getState()),
  );

export const useLayoutPanelsStore: StoreHook = Object.assign(useLayoutPanelsStoreImpl, {
  getState,
  setState,
});

