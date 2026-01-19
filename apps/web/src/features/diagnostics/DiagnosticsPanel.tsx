import type { DiagnosticsSnapshot } from './types';
import { formatBytes, formatPercent } from './format';
import type { CSSProperties } from 'react';

type Props = {
  snapshot: DiagnosticsSnapshot;
  onClose: () => void;
  onExport: () => void;
};

export function DiagnosticsPanel({ snapshot, onClose, onExport }: Props) {
  const { requests } = snapshot;
  const tileFailRate = formatPercent(requests.tileFailed, requests.tileTotal);
  const tileCacheHitRate = formatPercent(
    requests.tileCacheHits,
    requests.tileTotal
  );

  return (
    <aside
      data-testid="diagnostics-panel"
      style={{
        position: 'fixed',
        right: 12,
        bottom: 12,
        width: 360,
        maxWidth: 'calc(100vw - 24px)',
        background: 'rgba(17, 24, 39, 0.92)',
        color: '#f9fafb',
        border: '1px solid rgba(255, 255, 255, 0.12)',
        borderRadius: 12,
        padding: 12,
        fontFamily:
          'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
        fontSize: 12,
        lineHeight: 1.35,
        zIndex: 99999
      }}
    >
      <header style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <strong style={{ fontSize: 12, flex: 1 }}>Diagnostics</strong>
        <button
          type="button"
          onClick={onExport}
          style={buttonStyle}
          aria-label="Export diagnostics"
        >
          Export
        </button>
        <button
          type="button"
          onClick={onClose}
          style={buttonStyle}
          aria-label="Close diagnostics"
        >
          Close
        </button>
      </header>

      <section style={{ marginTop: 10 }}>
        <Row label="FPS" value={snapshot.fps != null ? `${snapshot.fps}` : 'N/A'} />
        <Row
          label="Memory"
          value={
            snapshot.memory
              ? `${formatBytes(snapshot.memory.usedBytes)} / ${formatBytes(
                  snapshot.memory.totalBytes ?? snapshot.memory.limitBytes
                )}`
              : 'N/A'
          }
        />
        <Row label="Requests" value={`${requests.total}`} />
        <Row label="Tile Requests" value={`${requests.tileTotal}`} />
        <Row
          label="Tile Fail"
          value={
            requests.tileTotal > 0
              ? `${requests.tileFailed}/${requests.tileTotal} (${tileFailRate})`
              : 'N/A'
          }
        />
        <Row
          label="Tile Cache Hit"
          value={
            requests.tileTotal > 0
              ? `${requests.tileCacheHits}/${requests.tileTotal} (${tileCacheHitRate})`
              : 'N/A'
          }
        />
        <Row label="Errors" value={`${snapshot.errorsTotal}`} />
      </section>

      <section style={{ marginTop: 10 }}>
        <details>
          <summary style={{ cursor: 'pointer' }}>
            Logs ({snapshot.requestLogs.length} req, {snapshot.errorLogs.length}{' '}
            err)
          </summary>
          <div style={{ marginTop: 8, maxHeight: 180, overflow: 'auto' }}>
            {snapshot.errorLogs.slice(-5).map((err) => (
              <pre
                key={err.at}
                style={{
                  margin: 0,
                  whiteSpace: 'pre-wrap',
                  color: '#fca5a5'
                }}
              >
                {new Date(err.at).toISOString()} {err.message}
              </pre>
            ))}
            {snapshot.requestLogs.slice(-5).map((req) => (
              <pre
                key={req.at}
                style={{
                  margin: 0,
                  whiteSpace: 'pre-wrap',
                  color: req.ok ? '#a7f3d0' : '#fca5a5'
                }}
              >
                {new Date(req.at).toISOString()} {req.method} {req.status ?? '-'}{' '}
                {req.isTile ? '[tile]' : ''} {req.url}
              </pre>
            ))}
          </div>
        </details>
      </section>
    </aside>
  );
}

function Row(props: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', gap: 8, padding: '2px 0' }}>
      <div style={{ width: 120, color: '#cbd5e1' }}>{props.label}</div>
      <div style={{ flex: 1, textAlign: 'right' }}>{props.value}</div>
    </div>
  );
}

const buttonStyle: CSSProperties = {
  background: 'rgba(255, 255, 255, 0.06)',
  border: '1px solid rgba(255, 255, 255, 0.12)',
  color: '#f9fafb',
  borderRadius: 8,
  padding: '4px 8px',
  cursor: 'pointer'
};
