const TILE_EXTENSIONS = new Set([
  '.png',
  '.jpg',
  '.jpeg',
  '.webp',
  '.avif',
  '.pbf',
  '.mvt',
  '.terrain',
  '.ktx2'
]);

export function isTileUrl(inputUrl: string): boolean {
  if (!inputUrl) return false;

  try {
    const url = new URL(inputUrl, globalThis.location?.href ?? 'http://localhost');
    const path = url.pathname.toLowerCase();

    if (path.includes('/tiles/')) return true;
    for (const ext of TILE_EXTENSIONS) {
      if (path.endsWith(ext)) return true;
    }

    const params = url.searchParams;
    const hasZxy =
      params.has('z') && params.has('x') && params.has('y') &&
      [params.get('z'), params.get('x'), params.get('y')].every((v) =>
        v ? /^\d+$/.test(v) : false
      );
    if (hasZxy) return true;

    return false;
  } catch {
    return false;
  }
}

