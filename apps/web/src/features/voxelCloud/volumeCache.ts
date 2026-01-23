import type { LocalModeBBox } from './bboxCalculator';

type CacheEntry = {
  data: ArrayBuffer;
  timestamp: number;
};

function decimalsForStep(step: number): number {
  if (!Number.isFinite(step) || step <= 0) return 0;
  const text = String(step);
  const expMatch = /e-(\d+)$/i.exec(text);
  if (expMatch) return Number(expMatch[1]) || 0;
  const dot = text.indexOf('.');
  if (dot === -1) return 0;
  return text.length - dot - 1;
}

function quantize(value: number, step: number): number {
  if (!Number.isFinite(value)) return 0;
  if (!Number.isFinite(step) || step <= 0) return value;
  return Math.round(value / step) * step;
}

function formatQuantized(value: number, step: number): string {
  const decimals = decimalsForStep(step);
  const fixed = quantize(value, step).toFixed(decimals);
  return decimals === 0 ? fixed : fixed.replace(/\.?0+$/, '');
}

export class VolumeCache {
  private readonly maxEntries: number;
  private readonly entries = new Map<string, CacheEntry>();

  constructor(maxEntries = 4) {
    this.maxEntries = Math.max(1, Math.floor(maxEntries));
  }

  static makeCacheKey(bbox: LocalModeBBox, levels: number[], res: number, validTime?: string): string {
    const bboxKey = [
      formatQuantized(bbox.west, 0.05),
      formatQuantized(bbox.south, 0.05),
      formatQuantized(bbox.east, 0.05),
      formatQuantized(bbox.north, 0.05),
      formatQuantized(bbox.bottom, 500),
      formatQuantized(bbox.top, 500),
    ].join(',');

    const levelsKey = levels.map((value) => Math.round(value)).join(',');
    const resKey = String(Math.round(res));
    const timeKey = validTime ? `|t=${validTime}` : '';
    return `${bboxKey}|${levelsKey}|${resKey}${timeKey}`;
  }

  get(key: string): ArrayBuffer | null {
    const entry = this.entries.get(key);
    if (!entry) return null;
    this.entries.delete(key);
    this.entries.set(key, entry);
    return entry.data;
  }

  set(key: string, data: ArrayBuffer): void {
    this.entries.delete(key);
    this.entries.set(key, { data, timestamp: Date.now() });

    while (this.entries.size > this.maxEntries) {
      const oldestKey = this.entries.keys().next().value as string | undefined;
      if (!oldestKey) break;
      this.entries.delete(oldestKey);
    }
  }

  clear(): void {
    this.entries.clear();
  }
}
