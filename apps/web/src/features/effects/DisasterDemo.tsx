import React from 'react';
import { createPortal } from 'react-dom';

import { fetchEffectPresets } from './api';
import { EffectCanvas } from './EffectCanvas';
import type { EffectPresetItem, EffectType } from './types';

type DisasterDemoProps = {
  apiBaseUrl: string;
};

const SUPPORTED_EFFECT: EffectType = 'debris_flow';

export function DisasterDemo({ apiBaseUrl }: DisasterDemoProps): React.JSX.Element {
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [presets, setPresets] = React.useState<EffectPresetItem[]>([]);
  const [selectedId, setSelectedId] = React.useState<string>('');
  const [isPlaying, setIsPlaying] = React.useState(false);

  React.useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchEffectPresets(apiBaseUrl, { signal: controller.signal })
      .then((all) => all.filter((p) => p.effect_type === SUPPORTED_EFFECT))
      .then((filtered) => {
        setPresets(filtered);
        setSelectedId(filtered[0]?.id ?? '');
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [apiBaseUrl]);

  const selectedPreset = React.useMemo(
    () => presets.find((p) => p.id === selectedId) ?? null,
    [presets, selectedId],
  );

  const canPlay = !!selectedPreset && !isPlaying;
  const canStop = isPlaying;

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>灾害特效</div>
        <div className="muted">
          从 <code>/api/v1/effects/presets</code> 拉取预设，当前仅演示{' '}
          <code>{SUPPORTED_EFFECT}</code>。
        </div>
      </div>

      {loading ? (
        <div className="muted">加载特效预设中…</div>
      ) : error ? (
        <>
          <div>预设加载失败</div>
          <div className="muted">{error}</div>
        </>
      ) : presets.length === 0 ? (
        <div className="muted">未找到 {SUPPORTED_EFFECT} 预设（请检查后端配置）</div>
      ) : (
        <>
          <div className="row" style={{ marginBottom: 12 }}>
            <label className="muted" htmlFor="preset">
              预设
            </label>
            <select
              id="preset"
              value={selectedId}
              onChange={(e) => {
                setSelectedId(e.target.value);
                setIsPlaying(false);
              }}
            >
              {presets.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.id}（L{p.intensity} / {p.risk_level}）
                </option>
              ))}
            </select>
          </div>

          {selectedPreset ? (
            <div className="muted" style={{ marginBottom: 12 }}>
              intensity={selectedPreset.intensity} spawn_rate={selectedPreset.spawn_rate}
              /s particle_size=[{selectedPreset.particle_size.min},{' '}
              {selectedPreset.particle_size.max}] wind={selectedPreset.wind_influence}{' '}
              duration={selectedPreset.duration || '∞'}s
            </div>
          ) : null}

          <div className="row" style={{ marginBottom: 12 }}>
            <button
              type="button"
              onClick={() => setIsPlaying(true)}
              disabled={!canPlay}
            >
              播放
            </button>
            <button
              type="button"
              onClick={() => setIsPlaying(false)}
              disabled={!canStop}
            >
              停止
            </button>
          </div>

          {selectedPreset ? (
            <div style={{ position: 'relative', height: 0 }}>
              <Portal targetId="effect-stage">
                <EffectCanvas
                  key={selectedPreset.id}
                  preset={selectedPreset}
                  isPlaying={isPlaying}
                  onAutoStop={() => setIsPlaying(false)}
                />
              </Portal>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

type PortalProps = { targetId: string; children: React.ReactNode };

function Portal({ targetId, children }: PortalProps): React.ReactPortal | null {
  const target = document.getElementById(targetId);
  if (!target) return null;
  return createPortal(children, target);
}
