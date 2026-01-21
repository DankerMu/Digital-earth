import { fetchJson, isHttpError } from '../../lib/http';
import {
  parseProductDetailResponse,
  parseProductsQueryResponse,
  type ProductDetail,
  type ProductsQueryResponse,
} from './productsTypes';

function normalizeApiBaseUrl(apiBaseUrl: string): string {
  return apiBaseUrl.trim().replace(/\/+$/, '');
}

const PRODUCTS_QUERY_CACHE_MAX_ENTRIES = 10;
const PRODUCTS_QUERY_CACHE_TTL_MS = 30_000;
const PRODUCT_DETAIL_CACHE_MAX_ENTRIES = 200;
const PRODUCT_DETAIL_CACHE_TTL_MS = 5 * 60_000;

type CacheEntry<T> = { value: T; expiresAt: number };

const productsQueryCache = new Map<string, CacheEntry<ProductsQueryResponse>>();
const productDetailCache = new Map<string, CacheEntry<ProductDetail>>();

function readCache<T>(cache: Map<string, CacheEntry<T>>, key: string): T | undefined {
  const entry = cache.get(key);
  if (!entry) return undefined;
  if (Date.now() >= entry.expiresAt) {
    cache.delete(key);
    return undefined;
  }

  cache.delete(key);
  cache.set(key, entry);
  return entry.value;
}

function writeCache<T>(
  cache: Map<string, CacheEntry<T>>,
  key: string,
  value: T,
  options: { maxEntries: number; ttlMs: number },
) {
  const entry: CacheEntry<T> = { value, expiresAt: Date.now() + options.ttlMs };
  cache.delete(key);
  cache.set(key, entry);

  while (cache.size > options.maxEntries) {
    const oldest = cache.keys().next().value as string | undefined;
    if (!oldest) break;
    cache.delete(oldest);
  }
}

export function clearProductsCache() {
  productsQueryCache.clear();
  productDetailCache.clear();
}

export async function getProductsQuery(options: {
  apiBaseUrl: string;
  signal?: AbortSignal;
  cache?: 'default' | 'no-cache';
}): Promise<ProductsQueryResponse> {
  const base = normalizeApiBaseUrl(options.apiBaseUrl);
  const url = new URL('/api/v1/products', base);
  const key = url.toString();
  const cached = options.cache !== 'no-cache' ? readCache(productsQueryCache, key) : undefined;
  if (cached) return cached;

  try {
    const payload = await fetchJson<unknown>(url.toString(), {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: options.signal,
      cache: options.cache === 'no-cache' ? 'no-store' : undefined,
    });
    const parsed = parseProductsQueryResponse(payload);
    writeCache(productsQueryCache, key, parsed, {
      maxEntries: PRODUCTS_QUERY_CACHE_MAX_ENTRIES,
      ttlMs: PRODUCTS_QUERY_CACHE_TTL_MS,
    });
    return parsed;
  } catch (error) {
    if (isHttpError(error)) {
      throw new Error(`Failed to load products: ${error.status}`, { cause: error });
    }
    throw error;
  }
}

export async function getProductDetail(options: {
  apiBaseUrl: string;
  productId: string;
  signal?: AbortSignal;
  cache?: 'default' | 'no-cache';
}): Promise<ProductDetail> {
  const base = normalizeApiBaseUrl(options.apiBaseUrl);
  const productId = options.productId.trim();
  const url = new URL(`/api/v1/products/${encodeURIComponent(productId)}`, base);
  const key = `${base}|${productId}`;
  const cached = options.cache !== 'no-cache' ? readCache(productDetailCache, key) : undefined;
  if (cached) return cached;

  try {
    const payload = await fetchJson<unknown>(url.toString(), {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: options.signal,
      cache: options.cache === 'no-cache' ? 'no-store' : undefined,
    });
    const parsed = parseProductDetailResponse(payload);
    writeCache(productDetailCache, key, parsed, {
      maxEntries: PRODUCT_DETAIL_CACHE_MAX_ENTRIES,
      ttlMs: PRODUCT_DETAIL_CACHE_TTL_MS,
    });
    return parsed;
  } catch (error) {
    if (isHttpError(error)) {
      throw new Error(`Failed to load product ${productId}: ${error.status}`, {
        cause: error,
      });
    }
    throw error;
  }
}
