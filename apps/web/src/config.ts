import { fetchJson } from './lib/http';

export type BasemapProviderMode = 'open' | 'ion' | 'selfHosted';
export type TerrainProviderMode = 'none' | 'ion' | 'selfHosted';

export type MapConfig = {
  basemapProvider?: BasemapProviderMode;
  terrainProvider?: TerrainProviderMode;
  cesiumIonAccessToken?: string;
  selfHosted?: {
    basemapUrlTemplate?: string;
    basemapScheme?: 'xyz' | 'tms';
    terrainUrl?: string;
  };
};

export type PublicConfig = {
  apiBaseUrl: string;
  map?: MapConfig;
};

let cachedConfig: PublicConfig | null = null;

export function clearConfigCache() {
  cachedConfig = null;
}

function parseBasemapProviderMode(value: unknown): BasemapProviderMode | undefined {
  if (value === 'open' || value === 'ion' || value === 'selfHosted') return value;
  if (value === 'self_hosted' || value === 'self-hosted') return 'selfHosted';
  return undefined;
}

function parseTerrainProviderMode(value: unknown): TerrainProviderMode | undefined {
  if (value === 'none' || value === 'ion' || value === 'selfHosted') return value;
  if (value === 'self_hosted' || value === 'self-hosted') return 'selfHosted';
  return undefined;
}

function parseOptionalString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function parseMapConfig(value: unknown): MapConfig | undefined {
  if (value === undefined || value === null) return undefined;
  if (!value || typeof value !== 'object') throw new Error('Invalid /config.json: map');

  const record = value as Record<string, unknown>;

  const basemapProvider = parseBasemapProviderMode(record.basemapProvider);
  const terrainProvider = parseTerrainProviderMode(record.terrainProvider);
  const cesiumIonAccessToken = parseOptionalString(record.cesiumIonAccessToken);

  let selfHosted: MapConfig['selfHosted'];
  if (record.selfHosted !== undefined && record.selfHosted !== null) {
    if (!record.selfHosted || typeof record.selfHosted !== 'object') {
      throw new Error('Invalid /config.json: map.selfHosted');
    }
    const selfRecord = record.selfHosted as Record<string, unknown>;
    const basemapSchemeRaw = parseOptionalString(selfRecord.basemapScheme);
    const basemapScheme =
      basemapSchemeRaw === 'xyz' || basemapSchemeRaw === 'tms'
        ? basemapSchemeRaw
        : undefined;

    selfHosted = {
      basemapUrlTemplate: parseOptionalString(selfRecord.basemapUrlTemplate),
      basemapScheme,
      terrainUrl: parseOptionalString(selfRecord.terrainUrl),
    };
  }

  const map: MapConfig = {};
  if (basemapProvider) map.basemapProvider = basemapProvider;
  if (terrainProvider) map.terrainProvider = terrainProvider;
  if (cesiumIonAccessToken) map.cesiumIonAccessToken = cesiumIonAccessToken;
  if (selfHosted) map.selfHosted = selfHosted;

  return Object.keys(map).length > 0 ? map : undefined;
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

  const map = parseMapConfig(record.map);
  cachedConfig = map
    ? { apiBaseUrl: record.apiBaseUrl, map }
    : { apiBaseUrl: record.apiBaseUrl };
  return cachedConfig;
}
