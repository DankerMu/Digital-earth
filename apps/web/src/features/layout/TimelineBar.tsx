import { useEffect, useMemo, useState } from 'react';

import { loadConfig } from '../../config';
import { GlassPanel } from '../../components/ui/GlassPanel';
import { DEFAULT_TIME_KEY, useTimeStore } from '../../state/time';
import { getEcmwfRunTimes, getEcmwfRuns } from '../catalog/ecmwfCatalogApi';
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

function toUtcIsoNoMillis(date: Date): string {
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

function addHoursUtcIso(baseUtcIso: string, hours: number): string {
  const base = new Date(baseUtcIso);
  if (Number.isNaN(base.getTime())) return baseUtcIso;
  return toUtcIsoNoMillis(new Date(base.getTime() + hours * 60 * 60 * 1000));
}

export function TimelineBar() {
  const runTimeKey = useTimeStore((state) => state.runTimeKey);
  const setRunTimeKey = useTimeStore((state) => state.setRunTimeKey);
  const setValidTimeKey = useTimeStore((state) => state.setValidTimeKey);

  const fallbackFrames = useMemo(() => makeHourlyFrames(DEFAULT_TIME_KEY, 24), []);
  const [frames, setFrames] = useState<Date[]>(fallbackFrames);
  const [initialIndex, setInitialIndex] = useState(0);
  const [controllerKey, setControllerKey] = useState<string>('fallback');
  const [apiBaseUrl, setApiBaseUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    void loadConfig()
      .then((config) => {
        if (cancelled) return null;
        setApiBaseUrl(config.apiBaseUrl);
        return getEcmwfRuns({ apiBaseUrl: config.apiBaseUrl, latest: 20, signal: controller.signal });
      })
      .then((result) => {
        if (cancelled) return;
        const latest = result?.runs[0]?.runTimeKey;
        if (!latest) return;
        const current = useTimeStore.getState().runTimeKey;
        if (result?.runs.some((run) => run.runTimeKey === current)) return;
        setRunTimeKey(latest);
      })
      .catch((error) => {
        if (cancelled) return;
        console.warn('[TimelineBar] failed to load ECMWF runs', error);
        setApiBaseUrl(null);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [setRunTimeKey]);

  useEffect(() => {
    if (!apiBaseUrl) return;
    if (!runTimeKey) return;

    let cancelled = false;
    const controller = new AbortController();

    void getEcmwfRunTimes({
      apiBaseUrl,
      runTimeKey,
      policy: 'std',
      signal: controller.signal,
    })
      .then((result) => {
        if (cancelled) return;
        const nextFrames = result.times
          .map((value) => new Date(value))
          .filter((value) => !Number.isNaN(value.getTime()));

        if (nextFrames.length === 0) {
          setFrames(fallbackFrames);
          setInitialIndex(0);
          setControllerKey(`fallback:${fallbackFrames.length}`);
          return;
        }

        const frameKeys = nextFrames.map(toUtcIsoNoMillis);
        const currentValidTimeKey = useTimeStore.getState().validTimeKey;
        const normalizedCurrentValid = currentValidTimeKey.replace(/\.\d{3}Z$/, 'Z');

        let nextIndex = frameKeys.indexOf(normalizedCurrentValid);
        let nextValidTimeKey = normalizedCurrentValid;

        if (nextIndex < 0) {
          const preferred = addHoursUtcIso(runTimeKey, 3);
          const preferredIndex = frameKeys.indexOf(preferred);
          if (preferredIndex >= 0) {
            nextIndex = preferredIndex;
            nextValidTimeKey = preferred;
          } else {
            nextIndex = 0;
            nextValidTimeKey = frameKeys[0] ?? normalizedCurrentValid;
          }

          if (nextValidTimeKey && nextValidTimeKey !== normalizedCurrentValid) {
            setValidTimeKey(nextValidTimeKey);
          }
        }

        setFrames(nextFrames);
        setInitialIndex(Math.max(0, nextIndex));
        setControllerKey(
          `${runTimeKey}:${nextFrames.length}:${nextFrames[0]!.getTime()}:${nextFrames[nextFrames.length - 1]!.getTime()}`,
        );
      })
      .catch((error) => {
        if (cancelled) return;
        console.warn('[TimelineBar] failed to load ECMWF run times', error);
        setFrames(fallbackFrames);
        setInitialIndex(0);
        setControllerKey(`fallback:${fallbackFrames.length}`);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [apiBaseUrl, fallbackFrames, runTimeKey, setValidTimeKey]);

  return (
    <GlassPanel className="h-16 px-4 flex items-center">
      <TimeController
        key={controllerKey}
        frames={frames}
        initialIndex={initialIndex}
        baseIntervalMs={1000}
        onRefreshLayers={(time) => {
          setValidTimeKey(toUtcIsoNoMillis(time));
        }}
      />
    </GlassPanel>
  );
}
