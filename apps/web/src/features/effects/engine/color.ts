export type Rgba = { r: number; g: number; b: number; a: number };

const RGBA_PATTERN =
  /^rgba\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*((?:0(?:\.\d+)?)|(?:1(?:\.0+)?))\s*\)$/i;

export function parseRgba(input: string): Rgba {
  const match = RGBA_PATTERN.exec(input.trim());
  if (!match) {
    throw new Error(`Invalid rgba() string: ${input}`);
  }

  const r = Number(match[1]);
  const g = Number(match[2]);
  const b = Number(match[3]);
  const a = Number(match[4]);

  if ([r, g, b].some((c) => c < 0 || c > 255)) {
    throw new Error(`Invalid rgba() channel range: ${input}`);
  }
  if (a < 0 || a > 1) {
    throw new Error(`Invalid rgba() alpha range: ${input}`);
  }

  return { r, g, b, a };
}

export function rgbaString(color: Rgba): string {
  return `rgba(${color.r}, ${color.g}, ${color.b}, ${color.a})`;
}

export function withAlpha(color: Rgba, alpha: number): Rgba {
  return { ...color, a: Math.max(0, Math.min(1, alpha)) };
}

