export type PublicConfig = {
  apiBaseUrl: string;
};

let cachedConfig: PublicConfig | null = null;

export async function loadConfig(): Promise<PublicConfig> {
  if (cachedConfig) return cachedConfig;

  const response = await fetch('/config.json', { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to load /config.json: ${response.status}`);
  }

  cachedConfig = (await response.json()) as PublicConfig;
  return cachedConfig;
}

