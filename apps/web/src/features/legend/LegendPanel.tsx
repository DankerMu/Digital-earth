import { useMemo } from 'react';

import { LAYER_META } from './layerMeta';
import { LegendScale } from './LegendScale';
import type { LayerType } from './types';
import { useLegendConfig } from './useLegendConfig';

export type LayerSelection = {
  id: string;
  type: LayerType;
  isVisible?: boolean;
  isPrimary?: boolean;
};

function pickPrimaryLayer(layers: LayerSelection[]): LayerSelection | null {
  const visible = layers.filter((layer) => layer.isVisible ?? true);
  if (visible.length === 0) return null;

  return visible.find((layer) => layer.isPrimary) ?? visible[0];
}

export function LegendPanel(props: { layers: LayerSelection[] }) {
  const primaryLayer = useMemo(() => pickPrimaryLayer(props.layers), [props.layers]);
  const layerType = primaryLayer?.type ?? null;

  const state = useLegendConfig(layerType);

  if (!layerType) {
    return (
      <div
        style={{
          borderRadius: 12,
          border: '1px solid rgba(148, 163, 184, 0.18)',
          background: 'rgba(15, 23, 42, 0.6)',
          padding: 12,
          color: 'rgba(226, 232, 240, 0.7)',
          fontSize: 13,
        }}
      >
        No active layer
      </div>
    );
  }

  const meta = LAYER_META[layerType];

  return (
    <aside
      aria-label="Legend"
      style={{
        borderRadius: 12,
        border: '1px solid rgba(148, 163, 184, 0.18)',
        background: 'rgba(15, 23, 42, 0.6)',
        padding: 12,
        backdropFilter: 'blur(8px)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          marginBottom: 8,
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600 }}>{meta.title}</div>
        <div style={{ fontSize: 12, color: 'rgba(226, 232, 240, 0.7)' }}>
          {meta.unit}
        </div>
      </div>

      {state.status === 'loading' ? (
        <div style={{ fontSize: 13, color: 'rgba(226, 232, 240, 0.7)' }}>
          Loading…
        </div>
      ) : null}

      {state.status === 'error' ? (
        <div style={{ fontSize: 13, color: 'rgb(248, 113, 113)' }}>
          {state.message}
        </div>
      ) : null}

      {state.status === 'loaded' ? (
        <div>
          <LegendScale legend={state.config} />
          <div
            style={{
              marginTop: 6,
              display: 'flex',
              justifyContent: 'space-between',
              fontSize: 12,
              color: 'rgba(226, 232, 240, 0.7)',
            }}
          >
            <span>
              {state.config.labels[0]} {meta.unit}
            </span>
            <span>
              {state.config.labels[state.config.labels.length - 1]} {meta.unit}
            </span>
          </div>
        </div>
      ) : null}
    </aside>
  );
}

