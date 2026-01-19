export function formatBytes(bytes: number | undefined): string {
  if (bytes == null || Number.isNaN(bytes)) return 'N/A';
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(1)} MB`;
  const gb = mb / 1024;
  return `${gb.toFixed(2)} GB`;
}

export function formatPercent(numerator: number, denominator: number): string {
  if (denominator <= 0) return 'N/A';
  const value = (numerator / denominator) * 100;
  return `${value.toFixed(1)}%`;
}

