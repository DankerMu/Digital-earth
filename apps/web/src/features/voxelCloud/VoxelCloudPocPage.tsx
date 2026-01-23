import {
  Cartesian3,
  EllipsoidTerrainProvider,
  ImageryLayer,
  UrlTemplateImageryProvider,
  Viewer,
  WebMercatorTilingScheme,
} from 'cesium';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import 'cesium/Build/Cesium/Widgets/widgets.css';

import { createFpsMonitor } from '../viewer/fpsMonitor';
import { VoxelCloudRenderer, type VoxelCloudSnapshot } from './VoxelCloudRenderer';

const DEFAULT_CAMERA = {
  longitude: 116.391,
  latitude: 39.9075,
  heightMeters: 3_000_000,
} as const;

const DEFAULT_VOLUME_URL = '/volumes/demo-voxel-cloud.volp';

type MemorySnapshot = {
  usedBytes: number | null;
  totalBytes: number | null;
};

function readMemorySnapshot(): MemorySnapshot {
  const perf = performance as unknown as {
    memory?: { usedJSHeapSize?: number; totalJSHeapSize?: number };
  };
  const used = typeof perf.memory?.usedJSHeapSize === 'number' ? perf.memory.usedJSHeapSize : null;
  const total = typeof perf.memory?.totalJSHeapSize === 'number' ? perf.memory.totalJSHeapSize : null;
  return { usedBytes: used, totalBytes: total };
}

function formatBytes(value: number | null): string {
  if (value == null) return '-';
  if (!Number.isFinite(value)) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = value;
  let unit = 0;
  while (v >= 1024 && unit < units.length - 1) {
    v /= 1024;
    unit += 1;
  }
  return `${v.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function clampNumber(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

export function VoxelCloudPocPage() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const rendererRef = useRef<VoxelCloudRenderer | null>(null);

  const [viewer, setViewer] = useState<Viewer | null>(null);
  const [volumeUrl, setVolumeUrl] = useState(DEFAULT_VOLUME_URL);
  const [snapshot, setSnapshot] = useState<VoxelCloudSnapshot>(() => ({
    ready: false,
    enabled: false,
    settings: {
      enabled: false,
      stepVoxels: 1,
      maxSteps: 128,
      densityMultiplier: 1.0,
      extinction: 1.2,
    },
    volume: null,
    recommended: null,
    metrics: null,
    lastError: null,
  }));

  const [fps, setFps] = useState<number | null>(null);
  const [memory, setMemory] = useState<MemorySnapshot>(() => readMemorySnapshot());
  const [loading, setLoading] = useState(false);

  const refreshSnapshot = useCallback(() => {
    const renderer = rendererRef.current;
    if (!renderer) return;
    setSnapshot(renderer.getSnapshot());
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const imageryProvider = new UrlTemplateImageryProvider({
      url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      tilingScheme: new WebMercatorTilingScheme(),
      maximumLevel: 18,
    });

    const newViewer = new Viewer(container, {
      baseLayer: new ImageryLayer(imageryProvider),
      terrainProvider: new EllipsoidTerrainProvider(),
      baseLayerPicker: false,
      geocoder: false,
      animation: false,
      timeline: false,
      fullscreenButton: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      infoBox: false,
      selectionIndicator: false,
      homeButton: true,
    });

    newViewer.scene.requestRenderMode = true;
    newViewer.scene.maximumRenderTimeChange = Infinity;

    newViewer.camera.setView({
      destination: Cartesian3.fromDegrees(
        DEFAULT_CAMERA.longitude,
        DEFAULT_CAMERA.latitude,
        DEFAULT_CAMERA.heightMeters,
      ),
    });

    setViewer(newViewer);
    return () => {
      setViewer(null);
      newViewer.destroy();
    };
  }, []);

  useEffect(() => {
    if (!viewer) return;

    const renderer = new VoxelCloudRenderer(viewer, { enabled: true });
    rendererRef.current = renderer;
    renderer.setEnabled(true);
    setSnapshot(renderer.getSnapshot());

    return () => {
      renderer.destroy();
      rendererRef.current = null;
    };
  }, [viewer]);

  useEffect(() => {
    if (!viewer) return;

    const monitor = createFpsMonitor({ sampleWindowMs: 1000, idleResetMs: 2500 });

    const onPostRender = () => {
      const sample = monitor.recordFrame(performance.now());
      if (sample != null) setFps(sample);
    };

    viewer.scene.postRender.addEventListener(onPostRender);
    return () => {
      viewer.scene.postRender.removeEventListener(onPostRender);
    };
  }, [viewer]);

  useEffect(() => {
    const handle = window.setInterval(() => setMemory(readMemorySnapshot()), 1500);
    return () => window.clearInterval(handle);
  }, []);

  const onLoadClick = useCallback(async () => {
    const renderer = rendererRef.current;
    if (!renderer) return;

    setLoading(true);
    try {
      await renderer.loadFromUrl(volumeUrl);
      renderer.setEnabled(true);
      refreshSnapshot();
    } catch {
      refreshSnapshot();
    } finally {
      setLoading(false);
    }
  }, [refreshSnapshot, volumeUrl]);

  const onToggleEnabled = useCallback(() => {
    const renderer = rendererRef.current;
    if (!renderer) return;
    renderer.setEnabled(!renderer.getSnapshot().enabled);
    refreshSnapshot();
  }, [refreshSnapshot]);

  const updateNumericSetting = useCallback(
    (key: 'stepVoxels' | 'maxSteps' | 'densityMultiplier' | 'extinction', value: number) => {
      const renderer = rendererRef.current;
      if (!renderer) return;

      if (key === 'stepVoxels') {
        renderer.updateSettings({ stepVoxels: clampNumber(value, 0.25, 4) });
      } else if (key === 'maxSteps') {
        renderer.updateSettings({ maxSteps: Math.round(clampNumber(value, 1, 512)) });
      } else if (key === 'densityMultiplier') {
        renderer.updateSettings({ densityMultiplier: clampNumber(value, 0, 10) });
      } else {
        renderer.updateSettings({ extinction: clampNumber(value, 0, 10) });
      }

      refreshSnapshot();
    },
    [refreshSnapshot],
  );

  const metrics = snapshot.metrics;
  const rec = snapshot.recommended;

  const derived = useMemo(() => {
    const approxCanvas = metrics?.approxAtlasBytes ?? null;
    const decodedBytes = metrics?.bytes ?? null;
    const total = approxCanvas != null && decodedBytes != null ? approxCanvas + decodedBytes : null;
    return { approxCanvas, decodedBytes, total };
  }, [metrics?.approxAtlasBytes, metrics?.bytes]);

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-slate-950 text-slate-100">
      <div ref={containerRef} className="absolute inset-0" />

      <div className="absolute left-4 top-4 w-[420px] rounded-xl border border-slate-400/20 bg-slate-950/80 p-4 backdrop-blur">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-sm font-semibold">[ST-0109] Voxel Cloud PoC</div>
            <div className="text-xs text-slate-300">
              Ray-marching via Cesium PostProcessStage · URL param: <code>?poc=voxel-cloud</code>
            </div>
          </div>
          <button
            type="button"
            className="rounded-md border border-slate-400/30 bg-slate-900/60 px-2 py-1 text-xs hover:bg-slate-900"
            onClick={onToggleEnabled}
            disabled={!snapshot.ready}
          >
            {snapshot.enabled ? 'Disable' : 'Enable'}
          </button>
        </div>

        <div className="mt-3 space-y-2 text-xs">
          <label className="block">
            <div className="mb-1 text-slate-300">Volume URL</div>
            <input
              value={volumeUrl}
              onChange={(e) => setVolumeUrl(e.target.value)}
              className="w-full rounded-md border border-slate-400/20 bg-slate-900/50 px-2 py-1 text-slate-100"
            />
          </label>

          <div className="flex gap-2">
            <button
              type="button"
              className="flex-1 rounded-md border border-slate-400/30 bg-sky-700/70 px-2 py-1 font-medium hover:bg-sky-700"
              onClick={onLoadClick}
              disabled={loading}
            >
              {loading ? 'Loading…' : 'Load'}
            </button>
            <button
              type="button"
              className="rounded-md border border-slate-400/30 bg-slate-900/60 px-2 py-1 hover:bg-slate-900"
              onClick={() => {
                rendererRef.current?.destroy();
                rendererRef.current = null;
                if (viewer) {
                  const renderer = new VoxelCloudRenderer(viewer, { enabled: snapshot.enabled });
                  rendererRef.current = renderer;
                  renderer.setEnabled(snapshot.enabled);
                  setSnapshot(renderer.getSnapshot());
                }
              }}
              disabled={!viewer}
              title="Recreate stage"
            >
              Reset
            </button>
          </div>

          <div className="grid grid-cols-2 gap-2 pt-2">
            <label className="block">
              <div className="mb-1 text-slate-300">Step (voxels)</div>
              <input
                type="number"
                value={snapshot.settings.stepVoxels}
                step={0.25}
                min={0.25}
                max={4}
                className="w-full rounded-md border border-slate-400/20 bg-slate-900/50 px-2 py-1"
                onChange={(e) => updateNumericSetting('stepVoxels', Number(e.target.value))}
              />
            </label>

            <label className="block">
              <div className="mb-1 text-slate-300">Max steps</div>
              <input
                type="number"
                value={snapshot.settings.maxSteps}
                step={1}
                min={1}
                max={512}
                className="w-full rounded-md border border-slate-400/20 bg-slate-900/50 px-2 py-1"
                onChange={(e) => updateNumericSetting('maxSteps', Number(e.target.value))}
              />
            </label>

            <label className="block">
              <div className="mb-1 text-slate-300">Density ×</div>
              <input
                type="number"
                value={snapshot.settings.densityMultiplier}
                step={0.1}
                min={0}
                max={10}
                className="w-full rounded-md border border-slate-400/20 bg-slate-900/50 px-2 py-1"
                onChange={(e) => updateNumericSetting('densityMultiplier', Number(e.target.value))}
              />
            </label>

            <label className="block">
              <div className="mb-1 text-slate-300">Extinction</div>
              <input
                type="number"
                value={snapshot.settings.extinction}
                step={0.1}
                min={0}
                max={10}
                className="w-full rounded-md border border-slate-400/20 bg-slate-900/50 px-2 py-1"
                onChange={(e) => updateNumericSetting('extinction', Number(e.target.value))}
              />
            </label>
          </div>

          <div className="mt-2 rounded-lg border border-slate-400/20 bg-slate-900/40 p-2">
            <div className="grid grid-cols-2 gap-x-3 gap-y-1">
              <div className="text-slate-300">FPS</div>
              <div>{fps ?? '-'}</div>
              <div className="text-slate-300">JS heap</div>
              <div>
                {formatBytes(memory.usedBytes)} / {formatBytes(memory.totalBytes)}
              </div>
              <div className="text-slate-300">Decoded bytes</div>
              <div>{formatBytes(derived.decodedBytes)}</div>
              <div className="text-slate-300">Atlas canvas</div>
              <div>{formatBytes(derived.approxCanvas)}</div>
              <div className="text-slate-300">Approx total</div>
              <div>{formatBytes(derived.total)}</div>
            </div>
          </div>

          {rec && (
            <div className="rounded-lg border border-slate-400/20 bg-slate-900/30 p-2">
              <div className="mb-1 text-slate-300">Recommended</div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-1">
                <div className="text-slate-300">Step (voxels)</div>
                <div>{rec.stepVoxels}</div>
                <div className="text-slate-300">Step (m)</div>
                <div>{rec.stepMeters == null ? '-' : rec.stepMeters.toFixed(2)}</div>
                <div className="text-slate-300">Max steps</div>
                <div>{rec.maxSteps}</div>
              </div>
            </div>
          )}

          {metrics && (
            <div className="rounded-lg border border-slate-400/20 bg-slate-900/30 p-2">
              <div className="mb-1 text-slate-300">Load metrics</div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-1">
                <div className="text-slate-300">Fetch</div>
                <div>{metrics.fetchMs.toFixed(1)} ms</div>
                <div className="text-slate-300">Decode</div>
                <div>{metrics.decodeMs.toFixed(1)} ms</div>
                <div className="text-slate-300">Atlas</div>
                <div>{metrics.atlasMs.toFixed(1)} ms</div>
                <div className="text-slate-300">Canvas</div>
                <div>{metrics.canvasMs.toFixed(1)} ms</div>
                <div className="text-slate-300">Total</div>
                <div>{metrics.totalMs.toFixed(1)} ms</div>
              </div>
            </div>
          )}

          {snapshot.lastError && (
            <div className="rounded-lg border border-red-500/30 bg-red-950/50 p-2 text-red-200">
              {snapshot.lastError}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
