import { useEffect } from 'react';

import { useLayoutPanelsStore } from '../../state/layoutPanels';
import type { LayerConfig } from '../../state/layerManager';
import { useLayerManagerStore } from '../../state/layerManager';
import { CesiumViewer } from '../viewer/CesiumViewer';
import { InfoPanel } from './InfoPanel';
import { LayerTree } from './LayerTree';
import { LegendPanel } from './LegendPanel';
import { TimelinePanel } from './TimelinePanel';

const DEFAULT_LAYERS: LayerConfig[] = [
  {
    id: 'temperature',
    type: 'temperature',
    variable: 'TMP',
    opacity: 1,
    visible: true,
    zIndex: 10,
  },
  {
    id: 'cloud',
    type: 'cloud',
    variable: 'cloud',
    opacity: 0.85,
    visible: false,
    zIndex: 20,
  },
  {
    id: 'precipitation',
    type: 'precipitation',
    variable: 'precipitation',
    opacity: 0.9,
    visible: false,
    zIndex: 30,
  },
  {
    id: 'wind',
    type: 'wind',
    variable: 'wind',
    opacity: 0.9,
    visible: false,
    zIndex: 40,
  },
];

export function AppLayout() {
  const isTimelineCollapsed = useLayoutPanelsStore((state) => state.timelineCollapsed);
  const isLayerTreeCollapsed = useLayoutPanelsStore((state) => state.layerTreeCollapsed);
  const isInfoPanelCollapsed = useLayoutPanelsStore((state) => state.infoPanelCollapsed);
  const isLegendCollapsed = useLayoutPanelsStore((state) => state.legendCollapsed);

  const toggleTimelineCollapsed = useLayoutPanelsStore((state) => state.toggleTimelineCollapsed);
  const toggleLayerTreeCollapsed = useLayoutPanelsStore((state) => state.toggleLayerTreeCollapsed);
  const toggleInfoPanelCollapsed = useLayoutPanelsStore((state) => state.toggleInfoPanelCollapsed);
  const toggleLegendCollapsed = useLayoutPanelsStore((state) => state.toggleLegendCollapsed);

  useEffect(() => {
    const state = useLayerManagerStore.getState();
    if (state.layers.length > 0) return;

    state.batch(() => {
      for (const layer of DEFAULT_LAYERS) {
        state.registerLayer(layer);
      }
    });
  }, []);

  return (
    <div className="h-screen w-screen bg-slate-950 text-slate-100">
      <div className="grid h-full grid-rows-[auto_1fr_auto] gap-3 p-3">
        <TimelinePanel
          collapsed={isTimelineCollapsed}
          onToggleCollapsed={toggleTimelineCollapsed}
        />

        <div className="flex min-h-0 gap-3">
          <div className={isLayerTreeCollapsed ? 'w-12' : 'w-[320px]'}>
            <LayerTree
              collapsed={isLayerTreeCollapsed}
              onToggleCollapsed={toggleLayerTreeCollapsed}
            />
          </div>

          <div className="flex-1 min-h-0 min-w-0 rounded-xl border border-slate-400/20 bg-slate-900/20">
            <CesiumViewer />
          </div>

          <div className={isInfoPanelCollapsed ? 'w-12' : 'w-[360px]'}>
            <InfoPanel
              collapsed={isInfoPanelCollapsed}
              onToggleCollapsed={toggleInfoPanelCollapsed}
            />
          </div>
        </div>

        <LegendPanel
          collapsed={isLegendCollapsed}
          onToggleCollapsed={toggleLegendCollapsed}
        />
      </div>
    </div>
  );
}
