import { parseProductDetailResponse, parseProductsQueryResponse, type ProductDetail, type ProductsQueryResponse } from './productsTypes';

function normalizeApiBaseUrl(apiBaseUrl: string): string {
  return apiBaseUrl.trim().replace(/\/+$/, '');
}

const productsQueryCache = new Map<string, ProductsQueryResponse>();
const productDetailCache = new Map<string, ProductDetail>();

export function clearProductsCache() {
  productsQueryCache.clear();
  productDetailCache.clear();
}

export async function getProductsQuery(options: {
  apiBaseUrl: string;
  signal?: AbortSignal;
}): Promise<ProductsQueryResponse> {
  const base = normalizeApiBaseUrl(options.apiBaseUrl);
  const url = new URL('/api/v1/products', base);
  const key = url.toString();
  const cached = productsQueryCache.get(key);
  if (cached) return cached;

  const response = await fetch(url.toString(), {
    method: 'GET',
    headers: { Accept: 'application/json' },
    signal: options.signal,
  });

  if (!response.ok) {
    throw new Error(`Failed to load products: ${response.status}`);
  }

  const payload = (await response.json()) as unknown;
  const parsed = parseProductsQueryResponse(payload);
  productsQueryCache.set(key, parsed);
  return parsed;
}

export async function getProductDetail(options: {
  apiBaseUrl: string;
  productId: string;
  signal?: AbortSignal;
}): Promise<ProductDetail> {
  const base = normalizeApiBaseUrl(options.apiBaseUrl);
  const productId = options.productId.trim();
  const url = new URL(`/api/v1/products/${encodeURIComponent(productId)}`, base);
  const key = `${base}|${productId}`;
  const cached = productDetailCache.get(key);
  if (cached) return cached;

  const response = await fetch(url.toString(), {
    method: 'GET',
    headers: { Accept: 'application/json' },
    signal: options.signal,
  });

  if (!response.ok) {
    throw new Error(`Failed to load product ${productId}: ${response.status}`);
  }

  const payload = (await response.json()) as unknown;
  const parsed = parseProductDetailResponse(payload);
  productDetailCache.set(key, parsed);
  return parsed;
}

