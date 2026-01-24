import { useMemo } from 'react';

import { GlassPanel } from '../../components/ui/GlassPanel';
import { DEFAULT_TIME_KEY, useTimeStore } from '../../state/time';
import { TimeController } from '../timeline/TimeController';

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

export function TimelineBar() {
  const frames = useMemo(() => makeHourlyFrames(DEFAULT_TIME_KEY, 24), []);
  const setTimeKey = useTimeStore((state) => state.setTimeKey);

  return (
    <GlassPanel className="h-16 px-4 flex items-center">
      <TimeController
        frames={frames}
        baseIntervalMs={1000}
        onRefreshLayers={(time) => {
          const iso = time.toISOString().replace(/\.\d{3}Z$/, 'Z');
          setTimeKey(iso);
        }}
      />
    </GlassPanel>
  );
}

