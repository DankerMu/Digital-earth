import { useEffect, useRef, useState, type CSSProperties } from 'react';

import { loadConfig } from '../../config';
import { TopNavBar } from '../../components/ui/TopNavBar';
import { useLayoutPanelsStore } from '../../state/layoutPanels';
import type { LayerConfig } from '../../state/layerManager';
import { useLayerManagerStore } from '../../state/layerManager';
import { AttributionBar } from '../attribution/AttributionBar';
import { HelpDialog } from '../help/HelpDialog';
import { CesiumViewer } from '../viewer/CesiumViewer';
import { InfoPanel } from './InfoPanel';
import { LayerPanel } from './LayerPanel';
import { TimelineBar } from './TimelineBar';

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
    variable: 'tcc',
    opacity: 0.45,
    visible: false,
    zIndex: 20,
  },
  {
    id: 'cloud-r-850',
    type: 'cloud',
    variable: 'humidity',
    level: 850,
    opacity: 0.28,
    visible: false,
    zIndex: 21,
  },
  {
    id: 'cloud-r-700',
    type: 'cloud',
    variable: 'humidity',
    level: 700,
    opacity: 0.24,
    visible: false,
    zIndex: 22,
  },
  {
    id: 'cloud-r-500',
    type: 'cloud',
    variable: 'humidity',
    level: 500,
    opacity: 0.2,
    visible: false,
    zIndex: 23,
  },
  {
    id: 'cloud-r-300',
    type: 'cloud',
    variable: 'humidity',
    level: 300,
    opacity: 0.16,
    visible: false,
    zIndex: 24,
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
  {
    id: 'snow-depth',
    type: 'snow-depth',
    variable: 'SNOD',
    opacity: 0.75,
    visible: false,
    zIndex: 50,
  },
];

export function AppLayout() {
  const appRootRef = useRef<HTMLDivElement | null>(null);
  const isLayerTreeCollapsed = useLayoutPanelsStore((state) => state.layerTreeCollapsed);
  const isInfoPanelCollapsed = useLayoutPanelsStore((state) => state.infoPanelCollapsed);

  const toggleLayerTreeCollapsed = useLayoutPanelsStore((state) => state.toggleLayerTreeCollapsed);
  const toggleInfoPanelCollapsed = useLayoutPanelsStore((state) => state.toggleInfoPanelCollapsed);
  const setInfoPanelCollapsed = useLayoutPanelsStore((state) => state.setInfoPanelCollapsed);

  const [helpOpen, setHelpOpen] = useState(false);
  const [apiBaseUrl, setApiBaseUrl] = useState<string | null>(null);

  useEffect(() => {
    const state = useLayerManagerStore.getState();
    const existingIds = new Set(state.layers.map((layer) => layer.id));

    state.batch(() => {
      for (const layer of DEFAULT_LAYERS) {
        if (existingIds.has(layer.id)) continue;
        state.registerLayer(layer);
      }
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    void loadConfig()
      .then((config) => {
        if (cancelled) return;
        setApiBaseUrl(config.apiBaseUrl);
      })
      .catch(() => {
        if (cancelled) return;
        setApiBaseUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const layerPanelWidthPx = isLayerTreeCollapsed ? 48 : 320;
  const infoPanelWidthPx = isInfoPanelCollapsed ? 48 : 360;

  return (
    <div
      ref={appRootRef}
      className="relative h-screen w-screen bg-slate-950 text-slate-100"
      style={
        {
          '--layer-panel-width': `${layerPanelWidthPx}px`,
          '--info-panel-width': `${infoPanelWidthPx}px`,
        } as CSSProperties
      }
    >
      <div className="absolute inset-0 z-0">
        <CesiumViewer />
      </div>

      <TopNavBar
        onOpenHelp={() => setHelpOpen(true)}
        onOpenSettings={() => setInfoPanelCollapsed(false)}
      />

      <div
        className={[
          'fixed left-4 top-24 bottom-24 z-40',
          isLayerTreeCollapsed ? 'w-12' : 'w-80',
        ].join(' ')}
      >
        <LayerPanel collapsed={isLayerTreeCollapsed} onToggleCollapsed={toggleLayerTreeCollapsed} />
      </div>

      <div
        className={[
          'fixed right-4 top-24 bottom-24 z-40',
          isInfoPanelCollapsed ? 'w-12' : 'w-[360px]',
        ].join(' ')}
      >
        <InfoPanel collapsed={isInfoPanelCollapsed} onToggleCollapsed={toggleInfoPanelCollapsed} />
      </div>

      <div className="fixed bottom-4 left-4 right-4 z-50">
        <TimelineBar />
      </div>

      {apiBaseUrl ? <AttributionBar apiBaseUrl={apiBaseUrl} /> : null}

      <HelpDialog open={helpOpen} onClose={() => setHelpOpen(false)} />
    </div>
  );
}
