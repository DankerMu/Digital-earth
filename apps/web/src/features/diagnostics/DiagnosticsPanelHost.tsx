import { useEffect, useMemo, useSyncExternalStore } from 'react';
import { DiagnosticsPanel } from './DiagnosticsPanel';
import { createDiagnosticsController } from './diagnosticsController';

export function DiagnosticsPanelHost() {
  const controller = useMemo(() => createDiagnosticsController(), []);
  const snapshot = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot
  );

  useEffect(() => {
    if (!snapshot.enabled) return;
    controller.start();
    return () => controller.stop();
  }, [controller, snapshot.enabled]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!event.ctrlKey || !event.shiftKey) return;
      if (event.code !== 'KeyD') return;
      event.preventDefault();
      controller.setEnabled(!snapshot.enabled);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [controller, snapshot.enabled]);

  if (!snapshot.enabled) return null;

  return (
    <DiagnosticsPanel
      snapshot={snapshot}
      onClose={() => controller.setEnabled(false)}
      onExport={() => downloadJson(controller.exportToJson())}
    />
  );
}

function downloadJson(json: string) {
  const blob = new Blob([json], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `diagnostics-${new Date()
    .toISOString()
    .replace(/[:.]/g, '-')}.json`;
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
