import { fetchJson } from './lib/http';

export type PublicConfig = {
  apiBaseUrl: string;
};

let cachedConfig: PublicConfig | null = null;

export function clearConfigCache() {
  cachedConfig = null;
}

export async function loadConfig(): Promise<PublicConfig> {
  if (cachedConfig) return cachedConfig;

  const data = await fetchJson<unknown>('/config.json', { cache: 'no-store' });
  if (!data || typeof data !== 'object') {
    throw new Error('Invalid /config.json');
  }

  const record = data as Record<string, unknown>;
  if (typeof record.apiBaseUrl !== 'string' || record.apiBaseUrl.length === 0) {
    throw new Error('Invalid /config.json: apiBaseUrl');
  }

  cachedConfig = { apiBaseUrl: record.apiBaseUrl };
  return cachedConfig;
}
