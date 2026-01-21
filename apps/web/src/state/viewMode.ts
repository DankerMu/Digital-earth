import { useSyncExternalStore } from 'react';

export type ViewModeId = 'global' | 'local' | 'event' | 'layerGlobal';

export const DEFAULT_VIEW_MODE_ID: ViewModeId = 'global';
const DEFAULT_ROUTE: ViewModeRoute = { viewModeId: 'global' };

export function isViewModeId(value: unknown): value is ViewModeId {
  return (
    value === 'global' ||
    value === 'local' ||
    value === 'event' ||
    value === 'layerGlobal'
  );
}

export type ViewModeRoute =
  | { viewModeId: 'global' }
  | { viewModeId: 'local'; lat: number; lon: number }
  | { viewModeId: 'event'; productId: string }
  | { viewModeId: 'layerGlobal'; layerId: string };

export type ViewModeSavedState = {
  local?: { lat: number; lon: number };
  event?: { productId: string };
  layerGlobal?: { layerId: string };
};

export type ViewModeTransition = {
  kind: 'forward' | 'back' | 'replace';
  from: ViewModeRoute;
  to: ViewModeRoute;
  token: number;
};

type ViewModeState = {
  viewModeId: ViewModeId;
  route: ViewModeRoute;
  history: ViewModeRoute[];
  saved: ViewModeSavedState;
  canGoBack: boolean;
  transition: ViewModeTransition | null;
  enterGlobal: () => void;
  enterLocal: (params: { lat: number; lon: number }) => void;
  enterEvent: (params: { productId: string }) => void;
  enterLayerGlobal: (params: { layerId: string }) => void;
  goBack: () => boolean;
  replaceRoute: (route: ViewModeRoute) => void;
  clearHistory: () => void;
};

const STORAGE_KEY = 'digital-earth.viewMode';
const MAX_HISTORY = 50;

type Listener = () => void;

const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) listener();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

type LatLon = { lat: number; lon: number };

function isLatLon(value: unknown): value is LatLon {
  if (!isRecord(value)) return false;
  const lat = value.lat;
  const lon = value.lon;
  if (!isFiniteNumber(lat) || !isFiniteNumber(lon)) return false;
  if (lat < -90 || lat > 90) return false;
  if (lon < -180 || lon > 180) return false;
  return true;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isViewModeRoute(value: unknown): value is ViewModeRoute {
  if (!isRecord(value)) return false;
  const viewModeId = value.viewModeId;
  if (!isViewModeId(viewModeId)) return false;

  if (viewModeId === 'global') return true;

  if (viewModeId === 'local') {
    return isLatLon(value);
  }

  if (viewModeId === 'event') {
    return isNonEmptyString(value.productId);
  }

  return isNonEmptyString(value.layerId);
}

function routesEqual(a: ViewModeRoute, b: ViewModeRoute): boolean {
  switch (a.viewModeId) {
    case 'global':
      return b.viewModeId === 'global';
    case 'local':
      return (
        b.viewModeId === 'local' &&
        Object.is(a.lat, b.lat) &&
        Object.is(a.lon, b.lon)
      );
    case 'event':
      return b.viewModeId === 'event' && a.productId === b.productId;
    case 'layerGlobal':
      return b.viewModeId === 'layerGlobal' && a.layerId === b.layerId;
  }
}

type PersistedViewModeState = {
  route: ViewModeRoute;
  history: ViewModeRoute[];
  saved: ViewModeSavedState;
};

function safeReadPersistedState(): PersistedViewModeState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return {
        route: DEFAULT_ROUTE,
        history: [],
        saved: {},
      };
    }

    const parsed = JSON.parse(raw) as unknown;
    if (!isRecord(parsed)) {
      return {
        route: DEFAULT_ROUTE,
        history: [],
        saved: {},
      };
    }

    const route = isViewModeRoute(parsed.route)
      ? parsed.route
      : DEFAULT_ROUTE;

    const history = Array.isArray(parsed.history)
      ? parsed.history.filter(isViewModeRoute).slice(-MAX_HISTORY)
      : [];

    const saved: ViewModeSavedState = {};
    if (isRecord(parsed.saved)) {
      const savedLocal = parsed.saved.local;
      if (isLatLon(savedLocal)) {
        saved.local = { lat: savedLocal.lat, lon: savedLocal.lon };
      }

      const savedEvent = parsed.saved.event;
      if (isRecord(savedEvent) && isNonEmptyString(savedEvent.productId)) {
        saved.event = { productId: savedEvent.productId };
      }

      const savedLayerGlobal = parsed.saved.layerGlobal;
      if (isRecord(savedLayerGlobal) && isNonEmptyString(savedLayerGlobal.layerId)) {
        saved.layerGlobal = { layerId: savedLayerGlobal.layerId };
      }
    }

    return { route, history, saved };
  } catch {
    return {
      route: DEFAULT_ROUTE,
      history: [],
      saved: {},
    };
  }
}

function safeWritePersistedState(next: PersistedViewModeState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // ignore write failures (e.g., disabled storage)
  }
}

function persist() {
  safeWritePersistedState({ route, history, saved });
}

function saveCurrentRoute() {
  const current = route;
  if (current.viewModeId === 'local') {
    saved = { ...saved, local: { lat: current.lat, lon: current.lon } };
    return;
  }

  if (current.viewModeId === 'event') {
    saved = { ...saved, event: { productId: current.productId } };
    return;
  }

  if (current.viewModeId === 'layerGlobal') {
    saved = { ...saved, layerGlobal: { layerId: current.layerId } };
  }
}

function transitionTo(
  nextRoute: ViewModeRoute,
  kind: ViewModeTransition['kind'],
  nextHistory: ViewModeRoute[],
) {
  if (routesEqual(route, nextRoute)) return;

  saveCurrentRoute();

  const from = route;
  route = nextRoute;
  history = nextHistory;

  transitionToken += 1;
  transition = { kind, from, to: nextRoute, token: transitionToken };

  persist();
  notify();
}

function pushRoute(nextRoute: ViewModeRoute) {
  const nextHistory = [...history, route].slice(-MAX_HISTORY);
  transitionTo(nextRoute, 'forward', nextHistory);
}

const enterGlobal: ViewModeState['enterGlobal'] = () => {
  pushRoute({ viewModeId: 'global' });
};

const enterLocal: ViewModeState['enterLocal'] = ({ lat, lon }) => {
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
  if (lat < -90 || lat > 90) return;
  if (lon < -180 || lon > 180) return;
  pushRoute({ viewModeId: 'local', lat, lon });
};

const enterEvent: ViewModeState['enterEvent'] = ({ productId }) => {
  if (!isNonEmptyString(productId)) return;
  pushRoute({ viewModeId: 'event', productId: productId.trim() });
};

const enterLayerGlobal: ViewModeState['enterLayerGlobal'] = ({ layerId }) => {
  if (!isNonEmptyString(layerId)) return;
  pushRoute({ viewModeId: 'layerGlobal', layerId: layerId.trim() });
};

const goBack: ViewModeState['goBack'] = () => {
  if (history.length === 0) return false;
  const previous = history[history.length - 1]!;
  const nextHistory = history.slice(0, -1);
  transitionTo(previous, 'back', nextHistory);
  return true;
};

const replaceRoute: ViewModeState['replaceRoute'] = (nextRoute) => {
  if (!isViewModeRoute(nextRoute)) return;
  transitionTo(nextRoute, 'replace', history);
};

const clearHistory: ViewModeState['clearHistory'] = () => {
  if (history.length === 0) return;
  history = [];
  transitionToken += 1;
  transition = { kind: 'replace', from: route, to: route, token: transitionToken };
  persist();
  notify();
};

const initial = safeReadPersistedState();

let route: ViewModeRoute = initial.route;
let history: ViewModeRoute[] = initial.history;
let saved: ViewModeSavedState = initial.saved;
let transition: ViewModeTransition | null = null;
let transitionToken = 0;

function getState(): ViewModeState {
  return {
    viewModeId: route.viewModeId,
    route,
    history,
    saved,
    canGoBack: history.length > 0,
    transition,
    enterGlobal,
    enterLocal,
    enterEvent,
    enterLayerGlobal,
    goBack,
    replaceRoute,
    clearHistory,
  };
}

function setState(
  partial: Partial<Pick<ViewModeState, 'route' | 'history' | 'saved'>>,
) {
  let didChange = false;

  if (partial.route && isViewModeRoute(partial.route) && !routesEqual(route, partial.route)) {
    route = partial.route;
    didChange = true;
  }

  if (partial.history && Array.isArray(partial.history)) {
    const nextHistory = partial.history.filter(isViewModeRoute).slice(-MAX_HISTORY);
    if (nextHistory.length !== history.length || nextHistory.some((item, idx) => item !== history[idx])) {
      history = nextHistory;
      didChange = true;
    }
  }

  if (partial.saved && isRecord(partial.saved)) {
    const nextSaved: ViewModeSavedState = {};
    const savedLocal = partial.saved.local;
    if (isLatLon(savedLocal)) {
      nextSaved.local = { lat: savedLocal.lat, lon: savedLocal.lon };
    }

    const savedEvent = partial.saved.event;
    if (isRecord(savedEvent) && isNonEmptyString(savedEvent.productId)) {
      nextSaved.event = { productId: savedEvent.productId };
    }

    const savedLayerGlobal = partial.saved.layerGlobal;
    if (isRecord(savedLayerGlobal) && isNonEmptyString(savedLayerGlobal.layerId)) {
      nextSaved.layerGlobal = { layerId: savedLayerGlobal.layerId };
    }

    if (
      nextSaved.local !== saved.local ||
      nextSaved.event !== saved.event ||
      nextSaved.layerGlobal !== saved.layerGlobal
    ) {
      saved = nextSaved;
      didChange = true;
    }
  }

  if (!didChange) return;
  persist();
  notify();
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

type Selector<T> = (state: ViewModeState) => T;

type StoreHook = {
  <T>(selector: Selector<T>): T;
  getState: typeof getState;
  setState: typeof setState;
};

const useViewModeStoreImpl = <T>(selector: Selector<T>): T =>
  useSyncExternalStore(
    subscribe,
    () => selector(getState()),
    () => selector(getState()),
  );

export const useViewModeStore: StoreHook = Object.assign(useViewModeStoreImpl, {
  getState,
  setState,
});
