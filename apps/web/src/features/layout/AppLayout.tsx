import { useEffect, useRef } from 'react';

import { useLayoutPanelsStore } from '../../state/layoutPanels';
import type { LayerConfig } from '../../state/layerManager';
import { useLayerManagerStore } from '../../state/layerManager';
import { CesiumViewer } from '../viewer/CesiumViewer';
import { DisclaimerLauncher } from '../disclaimer/DisclaimerLauncher';
import { HelpLauncher } from '../help/HelpLauncher';
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
    variable: 'tcc',
    opacity: 0.65,
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

  useEffect(() => {
    const root = appRootRef.current;
    if (!root) return;

    const cssVar = '--disclaimer-fab-offset-bottom';
    const extraOffsetPx = 8;

    let resizeObserver: ResizeObserver | null = null;
    let mutationObserver: MutationObserver | null = null;

    const observeCredits = (creditsElement: HTMLElement) => {
      resizeObserver = new ResizeObserver((entries) => {
        const entry = entries[0];
        const measuredHeight =
          entry?.contentRect?.height ?? creditsElement.getBoundingClientRect().height;
        const offset = Math.max(0, Math.ceil(measuredHeight + extraOffsetPx));
        root.style.setProperty(cssVar, `${offset}px`);
      });
      resizeObserver.observe(creditsElement);
    };

    const findCreditsElement = () =>
      document.querySelector<HTMLElement>('.cesium-widget-credits');

    const connect = () => {
      const creditsElement = findCreditsElement();
      if (!creditsElement) return false;
      observeCredits(creditsElement);
      return true;
    };

    if (!connect()) {
      mutationObserver = new MutationObserver(() => {
        if (resizeObserver) return;
        if (connect()) {
          mutationObserver?.disconnect();
          mutationObserver = null;
        }
      });
      mutationObserver.observe(document.body, { childList: true, subtree: true });
    }

    return () => {
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
      root.style.removeProperty(cssVar);
    };
  }, []);

  return (
    <div ref={appRootRef} className="h-screen w-screen bg-slate-950 text-slate-100">
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

      <HelpLauncher />
      <DisclaimerLauncher />
    </div>
  );
}
