import { fetchJson, isHttpError } from '../../lib/http';

function normalizeApiBaseUrl(apiBaseUrl: string): string {
  return apiBaseUrl.trim().replace(/\/+$/, '');
}

function toUtcIsoNoMillis(date: Date): string {
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function parseTimeKeyToUtcIso(value: unknown): string | null {
  if (!isNonEmptyString(value)) return null;
  const trimmed = value.trim();

  if (/^\d{8}T\d{6}Z$/.test(trimmed)) {
    const year = Number(trimmed.slice(0, 4));
    const month = Number(trimmed.slice(4, 6));
    const day = Number(trimmed.slice(6, 8));
    const hour = Number(trimmed.slice(9, 11));
    const minute = Number(trimmed.slice(11, 13));
    const second = Number(trimmed.slice(13, 15));
    const ms = Date.UTC(year, month - 1, day, hour, minute, second);
    const parsed = new Date(ms);
    return Number.isNaN(parsed.getTime()) ? null : toUtcIsoNoMillis(parsed);
  }

  const parsed = new Date(trimmed);
  return Number.isNaN(parsed.getTime()) ? null : toUtcIsoNoMillis(parsed);
}

export type EcmwfRunStatus = 'complete' | 'partial';

export type EcmwfRun = {
  runTimeKey: string;
  status: EcmwfRunStatus;
};

export type EcmwfRunsResponse = {
  runs: EcmwfRun[];
};

export async function getEcmwfRuns(options: {
  apiBaseUrl: string;
  latest?: number;
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
}): Promise<EcmwfRunsResponse> {
  const base = normalizeApiBaseUrl(options.apiBaseUrl);
  const url = new URL('/api/v1/catalog/ecmwf/runs', base);

  if (typeof options.latest === 'number') {
    url.searchParams.set('latest', String(options.latest));
  } else {
    if (typeof options.limit === 'number') url.searchParams.set('limit', String(options.limit));
    if (typeof options.offset === 'number') url.searchParams.set('offset', String(options.offset));
  }

  try {
    const payload = await fetchJson<unknown>(url.toString(), {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: options.signal,
    });

    const runs: EcmwfRun[] = [];
    if (isRecord(payload) && Array.isArray(payload.runs)) {
      for (const item of payload.runs) {
        if (!isRecord(item)) continue;
        const runTimeKey = parseTimeKeyToUtcIso(item.run_time);
        if (!runTimeKey) continue;
        const statusRaw = item.status;
        const status: EcmwfRunStatus = statusRaw === 'complete' ? 'complete' : 'partial';
        runs.push({ runTimeKey, status });
      }
    }

    return { runs };
  } catch (error) {
    if (isHttpError(error)) {
      throw new Error(`Failed to load ECMWF runs: ${error.status}`, { cause: error });
    }
    throw error;
  }
}

export type EcmwfRunTimesResponse = {
  times: string[];
  missing: string[];
};

export async function getEcmwfRunTimes(options: {
  apiBaseUrl: string;
  runTimeKey: string;
  policy?: 'std';
  signal?: AbortSignal;
}): Promise<EcmwfRunTimesResponse> {
  const base = normalizeApiBaseUrl(options.apiBaseUrl);
  const run = options.runTimeKey.trim();
  const url = new URL(`/api/v1/catalog/ecmwf/runs/${encodeURIComponent(run)}/times`, base);
  url.searchParams.set('policy', options.policy ?? 'std');

  try {
    const payload = await fetchJson<unknown>(url.toString(), {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: options.signal,
    });

    const times: string[] = [];
    const missing: string[] = [];

    if (isRecord(payload)) {
      if (Array.isArray(payload.times)) {
        for (const value of payload.times) {
          const parsed = parseTimeKeyToUtcIso(value);
          if (parsed) times.push(parsed);
        }
      }

      if (Array.isArray(payload.missing)) {
        for (const value of payload.missing) {
          if (isNonEmptyString(value)) missing.push(value.trim());
        }
      }
    }

    return { times, missing };
  } catch (error) {
    if (isHttpError(error)) {
      throw new Error(`Failed to load ECMWF run times: ${error.status}`, { cause: error });
    }
    throw error;
  }
}

export type EcmwfRunVarsResponse = {
  vars: string[];
  levels: string[];
  units: Record<string, string>;
  legendVersion: number;
};

export async function getEcmwfRunVars(options: {
  apiBaseUrl: string;
  runTimeKey: string;
  signal?: AbortSignal;
}): Promise<EcmwfRunVarsResponse> {
  const base = normalizeApiBaseUrl(options.apiBaseUrl);
  const run = options.runTimeKey.trim();
  const url = new URL(`/api/v1/catalog/ecmwf/runs/${encodeURIComponent(run)}/vars`, base);

  try {
    const payload = await fetchJson<unknown>(url.toString(), {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: options.signal,
    });

    if (!isRecord(payload)) {
      return { vars: [], levels: [], units: {}, legendVersion: 0 };
    }

    const vars: string[] = Array.isArray(payload.vars)
      ? payload.vars.filter(isNonEmptyString).map((value) => value.trim())
      : [];
    const levels: string[] = Array.isArray(payload.levels)
      ? payload.levels.filter(isNonEmptyString).map((value) => value.trim())
      : [];

    const units: Record<string, string> = {};
    if (isRecord(payload.units)) {
      for (const [key, value] of Object.entries(payload.units)) {
        if (!isNonEmptyString(key) || !isNonEmptyString(value)) continue;
        units[key.trim()] = value.trim();
      }
    }

    const legendRaw = payload.legend_version;
    const legendVersion = typeof legendRaw === 'number' && Number.isFinite(legendRaw) ? legendRaw : 0;

    return { vars, levels, units, legendVersion };
  } catch (error) {
    if (isHttpError(error)) {
      throw new Error(`Failed to load ECMWF run vars: ${error.status}`, { cause: error });
    }
    throw error;
  }
}
