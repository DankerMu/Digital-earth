import React from 'react';

import type { EffectPresetItem } from './types';

import { DebrisFlowEngine } from './engine/debrisFlow';

type EffectCanvasProps = {
  preset: EffectPresetItem;
  isPlaying: boolean;
  onAutoStop: () => void;
};

function getCanvasContext(canvas: HTMLCanvasElement): CanvasRenderingContext2D {
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    throw new Error('Canvas 2D context unavailable');
  }
  return ctx;
}

export function EffectCanvas({
  preset,
  isPlaying,
  onAutoStop,
}: EffectCanvasProps): React.JSX.Element {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const engineRef = React.useRef<DebrisFlowEngine | null>(null);
  const rafRef = React.useRef<number | null>(null);

  React.useEffect(() => {
    engineRef.current = new DebrisFlowEngine({
      preset,
      width: 1,
      height: 1,
    });
    return () => {
      engineRef.current = null;
    };
  }, [preset]);

  React.useEffect(() => {
    const element = containerRef.current;
    const canvas = canvasRef.current;
    if (!element || !canvas) return;

    const ctx = getCanvasContext(canvas);
    const dpr = Math.max(1, window.devicePixelRatio || 1);

    const observer = new ResizeObserver((entries) => {
      const engine = engineRef.current;
      if (!engine) return;
      const entry = entries[0];
      if (!entry) return;
      const { width, height } = entry.contentRect;
      if (!Number.isFinite(width) || !Number.isFinite(height)) return;
      if (width <= 1 || height <= 1) return;

      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      engine.resize(width, height);
      engine.render(ctx);
    });

    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    const engine = engineRef.current;
    if (!canvas || !engine) return;

    const ctx = getCanvasContext(canvas);
    let lastTs = performance.now();

    if (!isPlaying) {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      engine.reset();
      engine.render(ctx);
      return;
    }

    const tick = (ts: number) => {
      const dt = Math.max(0, Math.min(0.05, (ts - lastTs) / 1000));
      lastTs = ts;
      engine.tick(dt);
      engine.render(ctx);

      if (engine.isExpired()) {
        rafRef.current = null;
        onAutoStop();
        return;
      }
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [isPlaying, onAutoStop]);

  return (
    <div
      ref={containerRef}
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
      }}
    >
      <canvas
        ref={canvasRef}
        aria-label="effect-canvas"
        style={{
          position: 'absolute',
          inset: 0,
        }}
      />
    </div>
  );
}
