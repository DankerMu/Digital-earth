import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { prefetchNextFrameTiles } from '../layers/tilePrefetch';

export type PlaybackSpeed = 1 | 2 | 4;

export type TimeControllerProps = {
  frames: Date[];
  initialIndex?: number;
  baseIntervalMs?: number;
  dragDebounceMs?: number;
  onTimeChange?: (time: Date, index: number) => void;
  onRefreshLayers?: (time: Date, index: number) => void;
  loadFrame?: (time: Date, index: number, options?: { signal?: AbortSignal }) => Promise<void>;
};

const DEFAULT_DRAG_DEBOUNCE_MS = 400;

function clampIndex(index: number, length: number): number {
  if (length <= 0) return 0;
  return Math.min(Math.max(index, 0), length - 1);
}

function formatUtc(date: Date): string {
  return date.toISOString().slice(0, 16).replace('T', ' ');
}

function isAbortError(error: unknown): boolean {
  if (!error) return false;
  if (error instanceof DOMException) return error.name === 'AbortError';
  if (error instanceof Error) return error.name === 'AbortError';
  if (typeof error === 'object' && error !== null && 'name' in error) {
    return (error as { name?: unknown }).name === 'AbortError';
  }
  return false;
}

function toTimeKey(date: Date): string {
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export function TimeController({
  frames,
  initialIndex = 0,
  baseIntervalMs = 1000,
  dragDebounceMs = DEFAULT_DRAG_DEBOUNCE_MS,
  onTimeChange,
  onRefreshLayers,
  loadFrame
}: TimeControllerProps) {
  const framesSignature = useMemo(() => {
    let hash = 0;
    for (let i = 0; i < frames.length; i += 1) {
      hash = (hash * 31 + frames[i]!.getTime()) >>> 0;
    }
    return `${frames.length}:${hash}`;
  }, [frames]);

  const normalizedInitialIndex = useMemo(
    () => clampIndex(initialIndex, frames.length),
    [frames.length, initialIndex],
  );

  const [currentIndex, setCurrentIndex] = useState(normalizedInitialIndex);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<PlaybackSpeed>(1);
  const [isLoading, setIsLoading] = useState(false);

  const currentIndexRef = useRef(currentIndex);
  const isLoadingRef = useRef(isLoading);
  const requestIdRef = useRef(0);
  const dragTimerRef = useRef<number | null>(null);
  const loadAbortRef = useRef<AbortController | null>(null);
  const isPointerDownRef = useRef(false);
  const didPointerMoveRef = useRef(false);

  useEffect(() => {
    currentIndexRef.current = currentIndex;
  }, [currentIndex]);

  useEffect(() => {
    isLoadingRef.current = isLoading;
  }, [isLoading]);

  const cancelDragTimer = useCallback(() => {
    if (dragTimerRef.current == null) return;
    window.clearTimeout(dragTimerRef.current);
    dragTimerRef.current = null;
  }, []);

  const abortLoad = useCallback(() => {
    loadAbortRef.current?.abort();
    loadAbortRef.current = null;
  }, []);

  useEffect(() => {
    return () => {
      cancelDragTimer();
      abortLoad();
    };
  }, [abortLoad, cancelDragTimer]);

  useEffect(() => {
    const hasPendingDrag = dragTimerRef.current != null;
    const hasInFlightLoad = loadAbortRef.current != null;
    if (!hasPendingDrag && !hasInFlightLoad) return;

    cancelDragTimer();
    abortLoad();
    requestIdRef.current += 1;

    if (isLoadingRef.current) {
      isLoadingRef.current = false;
      setIsLoading(false);
    }
  }, [abortLoad, cancelDragTimer, framesSignature]);

  const goToIndex = useCallback(
    async (nextIndex: number, options?: { debounced?: boolean }): Promise<boolean> => {
      if (frames.length === 0) return false;

      const clamped = clampIndex(nextIndex, frames.length);
      if (clamped === currentIndexRef.current) return false;

      const nextTime = frames[clamped]!;

      currentIndexRef.current = clamped;
      setCurrentIndex(clamped);

      onTimeChange?.(nextTime, clamped);

      const shouldDebounce = options?.debounced === true;
      if (shouldDebounce) {
        cancelDragTimer();
        abortLoad();

        if (loadFrame) {
          isLoadingRef.current = true;
          setIsLoading(true);
        }

        const requestId = (requestIdRef.current += 1);
        dragTimerRef.current = window.setTimeout(() => {
          dragTimerRef.current = null;
          onRefreshLayers?.(nextTime, clamped);

          if (!loadFrame) return;

          abortLoad();
          const controller = new AbortController();
          loadAbortRef.current = controller;

          void loadFrame(nextTime, clamped, { signal: controller.signal })
            .catch((error) => {
              if (isAbortError(error)) return;
              console.error('[TimeController] loadFrame failed', error);
            })
            .finally(() => {
              if (controller.signal.aborted) return;
              if (requestIdRef.current !== requestId) return;
              if (loadAbortRef.current === controller) loadAbortRef.current = null;
              isLoadingRef.current = false;
              setIsLoading(false);
            });
        }, Math.max(0, dragDebounceMs));

        return true;
      }

      cancelDragTimer();
      onRefreshLayers?.(nextTime, clamped);

      if (!loadFrame) return true;

      abortLoad();

      const requestId = (requestIdRef.current += 1);
      isLoadingRef.current = true;
      setIsLoading(true);

      const controller = new AbortController();
      loadAbortRef.current = controller;

      try {
        await loadFrame(nextTime, clamped, { signal: controller.signal });
        return true;
      } catch (error) {
        if (!isAbortError(error)) {
          console.error('[TimeController] loadFrame failed', error);
        }
        return false;
      } finally {
        if (loadAbortRef.current === controller) loadAbortRef.current = null;
        if (requestIdRef.current === requestId) {
          isLoadingRef.current = false;
          setIsLoading(false);
        }
      }
    },
    [abortLoad, cancelDragTimer, dragDebounceMs, frames, loadFrame, onRefreshLayers, onTimeChange],
  );

  useEffect(() => {
    if (frames.length === 0) {
      setIsPlaying(false);
      setCurrentIndex(0);
      currentIndexRef.current = 0;
      return;
    }

    const clamped = clampIndex(currentIndexRef.current, frames.length);
    if (clamped !== currentIndexRef.current) {
      currentIndexRef.current = clamped;
      setCurrentIndex(clamped);
    }
  }, [frames.length]);

  useEffect(() => {
    if (!isPlaying) return;
    if (frames.length <= 1) return;

    const currentTime = frames[currentIndex];
    const nextTime = frames[currentIndex + 1];
    if (isLoadingRef.current) return;
    if (currentTime && nextTime) {
      prefetchNextFrameTiles({
        currentTimeKey: toTimeKey(currentTime),
        nextTimeKey: toTimeKey(nextTime),
      });
    }
  }, [currentIndex, frames, isPlaying]);

  useEffect(() => {
    if (!isPlaying) return;
    if (frames.length <= 1) return;

    const intervalMs = baseIntervalMs / speed;
    const intervalId = window.setInterval(() => {
      if (isLoadingRef.current) return;

      const nextIndex = currentIndexRef.current + 1;
      if (nextIndex >= frames.length) {
        setIsPlaying(false);
        return;
      }

      void goToIndex(nextIndex);
    }, intervalMs);

    return () => window.clearInterval(intervalId);
  }, [baseIntervalMs, frames.length, goToIndex, isPlaying, speed]);

  const currentTime = frames[currentIndex];
  const canStepBackward = currentIndex > 0 && frames.length > 0;
  const canStepForward = currentIndex < frames.length - 1 && frames.length > 0;

  const togglePlay = useCallback(() => {
    if (frames.length <= 1) return;

    if (!isPlaying && currentIndexRef.current >= frames.length - 1) {
      void goToIndex(0).then((didLoad) => {
        if (didLoad) setIsPlaying(true);
      });
      return;
    }

    setIsPlaying((p) => !p);
  }, [frames.length, goToIndex, isPlaying]);

  return (
    <div
      style={{
        width: '100%',
        background: 'rgba(15,23,42,0.8)',
        border: '1px solid rgba(148,163,184,0.2)',
        borderRadius: 12,
        padding: 12,
        backdropFilter: 'blur(10px)',
        display: 'flex',
        alignItems: 'center',
        gap: 12
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <button
          type="button"
          aria-label="上一帧"
          disabled={!canStepBackward}
          onClick={() => void goToIndex(currentIndexRef.current - 1)}
          style={{
            padding: '8px 10px',
            borderRadius: 10,
            border: '1px solid rgba(148,163,184,0.25)',
            background: canStepBackward ? 'transparent' : 'rgba(148,163,184,0.1)',
            color: '#cbd5e1',
            cursor: canStepBackward ? 'pointer' : 'not-allowed'
          }}
        >
          ◀
        </button>
        <button
          type="button"
          aria-label={isPlaying ? '暂停' : '播放'}
          onClick={togglePlay}
          style={{
            padding: '8px 12px',
            borderRadius: 10,
            border: '1px solid rgba(59,130,246,0.6)',
            background: isPlaying ? 'rgba(59,130,246,0.15)' : '#3b82f6',
            color: '#fff',
            cursor: frames.length > 1 ? 'pointer' : 'not-allowed'
          }}
        >
          {isPlaying ? '⏸' : '▶'}
        </button>
        <button
          type="button"
          aria-label="下一帧"
          disabled={!canStepForward}
          onClick={() => void goToIndex(currentIndexRef.current + 1)}
          style={{
            padding: '8px 10px',
            borderRadius: 10,
            border: '1px solid rgba(148,163,184,0.25)',
            background: canStepForward ? 'transparent' : 'rgba(148,163,184,0.1)',
            color: '#cbd5e1',
            cursor: canStepForward ? 'pointer' : 'not-allowed'
          }}
        >
          ▶
        </button>
      </div>

      <div style={{ minWidth: 190, textAlign: 'center' }}>
        <div style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}>
          {currentTime ? formatUtc(currentTime) : '--'}
        </div>
        <div style={{ fontSize: 12, color: '#94a3b8' }}>UTC</div>
      </div>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6 }}>
        <input
          aria-label="时间轴"
          type="range"
          min={0}
          max={Math.max(frames.length - 1, 0)}
          value={currentIndex}
          onPointerDown={(event) => {
            isPointerDownRef.current = true;
            didPointerMoveRef.current = false;
            event.currentTarget.setPointerCapture?.(event.pointerId);
          }}
          onPointerMove={() => {
            if (!isPointerDownRef.current) return;
            didPointerMoveRef.current = true;
          }}
          onPointerUp={() => {
            isPointerDownRef.current = false;
            didPointerMoveRef.current = false;
          }}
          onPointerCancel={() => {
            isPointerDownRef.current = false;
            didPointerMoveRef.current = false;
          }}
          onChange={(e) => {
            const next = Number(e.target.value);
            const debounced = isPointerDownRef.current && didPointerMoveRef.current;
            void goToIndex(next, { debounced });
          }}
          disabled={frames.length <= 1}
          style={{ width: '100%' }}
        />
        <div style={{ fontSize: 12, color: '#94a3b8' }}>
          {frames.length > 0 ? `${currentIndex + 1}/${frames.length}` : '无可用时间帧'}
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 12, color: '#94a3b8' }}>速度</span>
          <select
            aria-label="播放速度"
            value={speed}
            onChange={(e) => {
              const next = Number(e.target.value) as PlaybackSpeed;
              setSpeed(next);
            }}
            style={{
              padding: '6px 8px',
              borderRadius: 10,
              border: '1px solid rgba(148,163,184,0.25)',
              background: 'rgba(30,41,59,0.8)',
              color: '#e2e8f0'
            }}
          >
            <option value={1}>1x</option>
            <option value={2}>2x</option>
            <option value={4}>4x</option>
          </select>
        </label>

        {isLoading ? (
          <span
            aria-label="加载中"
            style={{ fontSize: 12, color: '#fbbf24', whiteSpace: 'nowrap' }}
          >
            加载中…
          </span>
        ) : null}
      </div>
    </div>
  );
}
