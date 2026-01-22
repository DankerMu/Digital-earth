import { useEventLayersStore, type EventLayerMode } from '../../state/eventLayers';

export type EventLayerModeStatus = 'idle' | 'loading' | 'loaded' | 'error';

const MODE_OPTIONS: Array<{ id: EventLayerMode; label: string }> = [
  { id: 'monitoring', label: '监测' },
  { id: 'history', label: '历史' },
  { id: 'difference', label: '差值' },
];

export type EventLayersToggleProps = {
  historyStatus?: EventLayerModeStatus;
  differenceStatus?: EventLayerModeStatus;
};

function statusLabel(status: EventLayerModeStatus): string | null {
  if (status === 'loading') return '加载中';
  if (status === 'error') return '不可用';
  return null;
}

export function EventLayersToggle({
  historyStatus = 'idle',
  differenceStatus = 'idle',
}: EventLayersToggleProps) {
  const enabled = useEventLayersStore((state) => state.enabled);
  const setEnabled = useEventLayersStore((state) => state.setEnabled);
  const mode = useEventLayersStore((state) => state.mode);
  const setMode = useEventLayersStore((state) => state.setMode);

  const statusByMode: Partial<Record<EventLayerMode, EventLayerModeStatus>> = {
    history: historyStatus,
    difference: differenceStatus,
  };

  return (
    <div className="eventLayersPanel">
      <div className="eventLayersHeader">
        <div className="eventLayersLabel">事件图层</div>
        <label className="eventLayersSwitch">
          <span className="eventLayersSwitchText">显示</span>
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
            aria-label="显示事件图层"
          />
        </label>
      </div>

      {enabled ? (
        <div className="eventLayersGroup" role="radiogroup" aria-label="事件图层切换">
          {MODE_OPTIONS.map((option) => {
            const status = statusByMode[option.id] ?? 'idle';
            const label = statusLabel(status);

            return (
              <button
                key={option.id}
                type="button"
                className="eventLayersButton"
                role="radio"
                aria-checked={option.id === mode}
                data-active={option.id === mode ? 'true' : 'false'}
                onClick={() => setMode(option.id)}
              >
                {option.label}
                {label ? <span className="eventLayersButtonStatus">（{label}）</span> : null}
              </button>
            );
          })}
        </div>
      ) : (
        <div className="eventLayersHelp">关闭后隐藏，避免信息过载。</div>
      )}
    </div>
  );
}
