import { fetchJson, isHttpError } from '../../lib/http';
import type { BBox } from '../products/productsTypes';
import { parseRiskEvaluateResponse, parseRiskPoisQueryResponse, splitBBoxAtDateline } from './riskTypes';
import type { RiskEvaluateResponse, RiskPOI } from './riskTypes';

function normalizeApiBaseUrl(apiBaseUrl: string): string {
  return apiBaseUrl.trim().replace(/\/+$/, '');
}

async function getRiskPoisPage(options: {
  apiBaseUrl: string;
  bbox: BBox;
  page: number;
  pageSize: number;
  signal?: AbortSignal;
}): Promise<{ items: RiskPOI[]; total: number }> {
  const base = normalizeApiBaseUrl(options.apiBaseUrl);
  const url = new URL('/api/v1/risk/pois', base);
  url.searchParams.set(
    'bbox',
    `${options.bbox.min_x},${options.bbox.min_y},${options.bbox.max_x},${options.bbox.max_y}`,
  );
  url.searchParams.set('page', String(options.page));
  url.searchParams.set('page_size', String(options.pageSize));

  try {
    const payload = await fetchJson<unknown>(url.toString(), {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: options.signal,
    });
    const parsed = parseRiskPoisQueryResponse(payload);
    return { items: parsed.items, total: parsed.total };
  } catch (error) {
    if (isHttpError(error)) {
      throw new Error(`Failed to load risk POIs: ${error.status}`, { cause: error });
    }
    throw error;
  }
}

export async function getRiskPois(options: {
  apiBaseUrl: string;
  bbox: BBox;
  signal?: AbortSignal;
  pageSize?: number;
  maxPages?: number;
}): Promise<RiskPOI[]> {
  const pageSize = options.pageSize ?? 1000;
  const maxPages = options.maxPages ?? 20;

  const bboxes = splitBBoxAtDateline(options.bbox);
  const itemsById = new Map<number, RiskPOI>();

  for (const bbox of bboxes) {
    let page = 1;
    let fetched = 0;
    let total = Infinity;

    while (page <= maxPages && fetched < total) {
      const response = await getRiskPoisPage({
        apiBaseUrl: options.apiBaseUrl,
        bbox,
        page,
        pageSize,
        signal: options.signal,
      });

      total = response.total;
      fetched += response.items.length;
      for (const item of response.items) itemsById.set(item.id, item);

      if (response.items.length === 0) break;
      page += 1;
    }
  }

  return [...itemsById.values()].sort((a, b) => a.id - b.id);
}

export async function evaluateRisk(options: {
  apiBaseUrl: string;
  productId: string | number;
  validTime: string;
  poiIds?: number[] | null;
  bbox?: [number, number, number, number] | null;
  signal?: AbortSignal;
}): Promise<RiskEvaluateResponse> {
  const mergeEvaluateResponses = (responses: RiskEvaluateResponse[]): RiskEvaluateResponse => {
    const resultsById = new Map<number, RiskEvaluateResponse['results'][number]>();
    let duration_ms = 0;
    const reasons: Record<string, number> = {};

    for (const response of responses) {
      duration_ms += response.summary.duration_ms;
      for (const [key, value] of Object.entries(response.summary.reasons)) {
        reasons[key] = (reasons[key] ?? 0) + value;
      }
      for (const result of response.results) {
        resultsById.set(result.poi_id, result);
      }
    }

    const results = [...resultsById.values()].sort((a, b) => a.poi_id - b.poi_id);
    const level_counts: Record<string, number> = {};
    let max_level: number | null = null;
    let sumScore = 0;

    for (const result of results) {
      const key = String(Math.round(result.level));
      level_counts[key] = (level_counts[key] ?? 0) + 1;
      max_level = max_level == null ? result.level : Math.max(max_level, result.level);
      sumScore += result.score;
    }

    return {
      results,
      summary: {
        total: results.length,
        duration_ms,
        level_counts,
        reasons,
        max_level,
        avg_score: results.length ? sumScore / results.length : null,
      },
    };
  };

  const evaluateRiskOnce = async (options: {
    apiBaseUrl: string;
    productId: string | number;
    validTime: string;
    poiIds?: number[] | null;
    bbox?: [number, number, number, number] | null;
    signal?: AbortSignal;
  }): Promise<RiskEvaluateResponse> => {
  const base = normalizeApiBaseUrl(options.apiBaseUrl);
  const url = new URL('/api/v1/risk/evaluate', base);

  const productId =
    typeof options.productId === 'number'
      ? options.productId
      : Number.parseInt(options.productId.trim(), 10);

  if (!Number.isFinite(productId) || productId <= 0) {
    throw new Error('Invalid productId');
  }

  const payloadBody: Record<string, unknown> = {
    product_id: productId,
    valid_time: options.validTime,
  };

  if (options.poiIds != null) {
    payloadBody.poi_ids = options.poiIds;
  }
  if (options.bbox != null) {
    payloadBody.bbox = options.bbox;
  }

  try {
    const payload = await fetchJson<unknown>(url.toString(), {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(payloadBody),
      signal: options.signal,
    });
    return parseRiskEvaluateResponse(payload);
  } catch (error) {
    if (isHttpError(error)) {
      throw new Error(`Failed to evaluate risk: ${error.status}`, { cause: error });
    }
    throw error;
  }
  };

  if (options.poiIds == null && options.bbox != null) {
    const bboxes = splitBBoxAtDateline({
      min_x: options.bbox[0],
      min_y: options.bbox[1],
      max_x: options.bbox[2],
      max_y: options.bbox[3],
    });

    if (bboxes.length > 1) {
      const responses = await Promise.all(
        bboxes.map((bbox) =>
          evaluateRiskOnce({
            ...options,
            bbox: [bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y],
          }),
        ),
      );

      return mergeEvaluateResponses(responses);
    }
  }

  return evaluateRiskOnce(options);
}
