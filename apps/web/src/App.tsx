import { useMemo, useState } from 'react';

import { LegendPanel, type LayerSelection } from './features/legend/LegendPanel';
import { SUPPORTED_LAYER_TYPES, type LayerType } from './features/legend/types';

function buildDefaultLayers(): LayerSelection[] {
  return SUPPORTED_LAYER_TYPES.map((type) => ({
    id: type,
    type,
    isVisible: type === 'temperature',
    isPrimary: type === 'temperature',
  }));
}

export default function App() {
  const [layers, setLayers] = useState<LayerSelection[]>(() => buildDefaultLayers());

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
      </div>

      <div className="legend-shell">
        <LegendPanel layers={layers} />
      </div>
    </div>
  );
}
