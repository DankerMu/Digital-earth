export type AttributionPayload = {
  text: string;
  etag: string | null;
  version: string | null;
};

let cached: AttributionPayload | null = null;

function resolveAttributionUrl(apiBaseUrl: string): string {
  const base = apiBaseUrl?.trim() ? apiBaseUrl.trim() : window.location.origin;
  return new URL('/api/v1/attribution', base).toString();
}

export async function fetchAttribution(
  apiBaseUrl: string
): Promise<AttributionPayload> {
  const headers: HeadersInit = {};
  if (cached?.etag) headers['If-None-Match'] = cached.etag;

  const response = await fetch(resolveAttributionUrl(apiBaseUrl), { headers });
  if (response.status === 304 && cached) return cached;
  if (!response.ok) {
    throw new Error(`Failed to fetch attribution: ${response.status}`);
  }

  const text = await response.text();
  cached = {
    text,
    etag: response.headers.get('ETag'),
    version: response.headers.get('X-Attribution-Version'),
  };
  return cached;
}

export function clearAttributionCache(): void {
  cached = null;
}

