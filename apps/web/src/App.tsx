import { useMemo, useState } from 'react';

import ErrorBoundary from './components/ErrorBoundary';
import { LegendPanel, type LayerSelection } from './features/legend/LegendPanel';
import { SUPPORTED_LAYER_TYPES, type LayerType } from './features/legend/types';
import { TimeController } from './features/timeline/TimeController';
import { CesiumViewer } from './features/viewer/CesiumViewer';

function buildDefaultLayers(): LayerSelection[] {
  return SUPPORTED_LAYER_TYPES.map((type) => ({
    id: type,
    type,
    isVisible: type === 'temperature',
    isPrimary: type === 'temperature',
  }));
}

function makeHourlyFrames(baseUtcIso: string, count: number): Date[] {
  const base = new Date(baseUtcIso);
  if (Number.isNaN(base.getTime())) {
    throw new Error(`Invalid baseUtcIso: ${baseUtcIso}`);
  }

  const frames: Date[] = [];
  for (let i = 0; i < count; i += 1) {
    frames.push(new Date(base.getTime() + i * 60 * 60 * 1000));
  }
  return frames;
}

function AppContent() {
  const [layers, setLayers] = useState<LayerSelection[]>(() => buildDefaultLayers());
  const [activeTimeIndex, setActiveTimeIndex] = useState(0);
  const [layerRefreshToken, setLayerRefreshToken] = useState(0);

  const frames = useMemo(() => makeHourlyFrames('2024-01-15T00:00:00Z', 24), []);

  const visibleLayers = useMemo(
    () => layers.filter((layer) => layer.isVisible),
    [layers],
  );

  function setLayerVisibility(type: LayerType, isVisible: boolean) {
    setLayers((prev) => {
      const next = prev.map((layer) =>
        layer.type === type ? { ...layer, isVisible } : layer,
      );

      const stillHasPrimary = next.some((layer) => layer.isVisible && layer.isPrimary);
      if (stillHasPrimary) return next;

      const firstVisible = next.find((layer) => layer.isVisible);
      return next.map((layer) => ({
        ...layer,
        isPrimary: firstVisible ? layer.id === firstVisible.id : false,
      }));
    });
  }

  function setPrimaryLayer(type: LayerType) {
    setLayers((prev) =>
      prev.map((layer) => ({
        ...layer,
        isPrimary: layer.type === type,
      })),
    );
  }

  return (
    <div className="app">
      <div className="controls">
        <h1>Legend Demo</h1>
        <div className="layer-grid">
          {SUPPORTED_LAYER_TYPES.map((type) => {
            const layer = layers.find((item) => item.type === type);
            if (!layer) return null;

            return (
              <label key={type} className="control-row">
                <span>{type}</span>
                <input
                  type="checkbox"
                  checked={layer.isVisible}
                  onChange={(event) => setLayerVisibility(type, event.target.checked)}
                />
              </label>
            );
          })}
        </div>

        <label className="control-row">
          <span>Primary</span>
          <select
            value={layers.find((layer) => layer.isPrimary)?.type ?? ''}
            onChange={(event) => setPrimaryLayer(event.target.value as LayerType)}
            disabled={visibleLayers.length === 0}
          >
            {visibleLayers.map((layer) => (
              <option key={layer.id} value={layer.type}>
                {layer.type}
              </option>
            ))}
          </select>
        </label>

        <div className="control-row">
          <span>Frame</span>
          <span>
            {frames.length > 0 ? `${activeTimeIndex + 1}/${frames.length}` : '--'}
          </span>
        </div>

        <div className="control-row">
          <span>Layer refresh</span>
          <span>{layerRefreshToken}</span>
        </div>

        <TimeController
          frames={frames}
          baseIntervalMs={1000}
          onTimeChange={(_, nextIndex) => {
            setActiveTimeIndex(nextIndex);
          }}
          onRefreshLayers={() => {
            setLayerRefreshToken((token) => token + 1);
          }}
        />
      </div>

      <div className="viewer-shell">
        <CesiumViewer />
      </div>

      <div className="legend-shell">
        <LegendPanel layers={layers} />
      </div>
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <AppContent />
    </ErrorBoundary>
  );
}
