import { useMemo, useState } from 'react';

import { DEFAULT_TIME_KEY, useTimeStore } from '../../state/time';
import { TimeController } from '../timeline/TimeController';

export type TimelinePanelProps = {
  collapsed: boolean;
  onToggleCollapsed: () => void;
};

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

export function TimelinePanel({ collapsed, onToggleCollapsed }: TimelinePanelProps) {
  const [activeTimeIndex, setActiveTimeIndex] = useState(0);
  const frames = useMemo(() => makeHourlyFrames(DEFAULT_TIME_KEY, 24), []);
  const setTimeKey = useTimeStore((state) => state.setTimeKey);

  return (
    <section
      aria-label="Timeline"
      className="rounded-xl border border-slate-400/20 bg-slate-800/80 shadow-lg backdrop-blur-xl"
    >
      <header className="flex items-center justify-between gap-3 px-4 py-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-white">时间轴</div>
          <div className="text-xs text-slate-400">
            {frames.length > 0 ? `${activeTimeIndex + 1}/${frames.length}` : '--'}
          </div>
        </div>

        <button
          type="button"
          className="rounded-lg border border-slate-400/20 bg-slate-700/30 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
          aria-label={collapsed ? '展开时间轴' : '折叠时间轴'}
          onClick={onToggleCollapsed}
        >
          {collapsed ? '展开' : '折叠'}
        </button>
      </header>

      {collapsed ? null : (
        <div className="px-4 pb-4">
          <TimeController
            frames={frames}
            baseIntervalMs={1000}
            onTimeChange={(_, nextIndex) => setActiveTimeIndex(nextIndex)}
            onRefreshLayers={(time) => {
              const iso = time.toISOString().replace(/\.\d{3}Z$/, 'Z');
              setTimeKey(iso);
            }}
          />
        </div>
      )}
    </section>
  );
}
