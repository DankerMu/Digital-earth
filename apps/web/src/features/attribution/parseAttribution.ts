export type ParsedAttribution = {
  title: string | null;
  updatedAt: string | null;
  sources: string[];
  disclaimer: string[];
};

function findLineIndex(lines: string[], match: string): number {
  return lines.findIndex((line) => line.trim() === match);
}

function collectBullets(lines: string[], startIndex: number): string[] {
  const items: string[] = [];
  for (let i = startIndex; i < lines.length; i += 1) {
    const trimmed = lines[i].trim();
    if (!trimmed) continue;
    if (trimmed === 'Sources:' || trimmed === 'Disclaimer:') break;
    if (trimmed.startsWith('- ')) items.push(trimmed.slice(2).trim());
  }
  return items;
}

export function parseAttribution(text: string): ParsedAttribution {
  const lines = text.split(/\r?\n/);
  const title = lines.find((line) => line.trim())?.trim() ?? null;
  const updatedAt =
    lines.find((line) => line.trim().startsWith('Updated:'))?.trim() ?? null;

  const sourcesIndex = findLineIndex(lines, 'Sources:');
  const disclaimerIndex = findLineIndex(lines, 'Disclaimer:');

  const sources =
    sourcesIndex >= 0
      ? collectBullets(lines, sourcesIndex + 1)
      : ([] as string[]);
  const disclaimer =
    disclaimerIndex >= 0
      ? collectBullets(lines, disclaimerIndex + 1)
      : ([] as string[]);

  return { title, updatedAt, sources, disclaimer };
}

export function parseAttributionSummary(text: string): string {
  const parsed = parseAttribution(text);
  if (!parsed.sources.length) return '© Cesium';

  const credits = parsed.sources
    .map((line) => {
      const withoutSuffix = line.split(' (')[0]?.trim() ?? '';
      const left = withoutSuffix.split(' — ')[0]?.trim() ?? '';
      return left;
    })
    .filter(Boolean);

  if (!credits.length) return '© Cesium';
  return credits.join(' · ');
}

