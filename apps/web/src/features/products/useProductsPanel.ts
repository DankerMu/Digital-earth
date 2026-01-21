import { useCallback, useEffect, useState } from 'react';

import { loadConfig } from '../../config';
import { clearProductsCache, getProductDetail, getProductsQuery } from './productsApi';
import type { ProductDetail, ProductSummary } from './productsTypes';

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded' }
  | { status: 'error'; message: string };

const PRODUCT_DETAIL_FETCH_CONCURRENCY = 4;

export type ProductsPanelState = {
  list: LoadState;
  detailsStatus: 'idle' | 'loading' | 'loaded';
  items: ProductSummary[];
  detailsById: Record<string, ProductDetail>;
  reload: () => void;
};

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim() !== '') return error.message;
  return 'Unknown error';
}

export function useProductsPanel(): ProductsPanelState {
  const [loadToken, setLoadToken] = useState(0);
  const [list, setList] = useState<LoadState>({ status: 'loading' });
  const [detailsStatus, setDetailsStatus] = useState<'idle' | 'loading' | 'loaded'>('idle');
  const [items, setItems] = useState<ProductSummary[]>([]);
  const [detailsById, setDetailsById] = useState<Record<string, ProductDetail>>({});

  const reload = useCallback(() => {
    clearProductsCache();
    setLoadToken((token) => token + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();

    setList({ status: 'loading' });
    setDetailsStatus('idle');
    setItems([]);
    setDetailsById({});

    void (async () => {
      try {
        const { apiBaseUrl } = await loadConfig();
        const products = await getProductsQuery({
          apiBaseUrl,
          signal: controller.signal,
        });

        if (controller.signal.aborted) return;

        setItems(products.items);
        setList({ status: 'loaded' });

        if (products.items.length === 0) {
          setDetailsStatus('loaded');
          return;
        }

        setDetailsStatus('loading');
        const nextDetails: Record<string, ProductDetail> = {};
        let flushScheduled = false;

        const scheduleFlush = () => {
          if (flushScheduled) return;
          flushScheduled = true;
          queueMicrotask(() => {
            flushScheduled = false;
            if (controller.signal.aborted) return;
            setDetailsById({ ...nextDetails });
          });
        };

        let index = 0;
        const worker = async () => {
          while (true) {
            if (controller.signal.aborted) return;
            const current = index;
            index += 1;
            if (current >= products.items.length) return;

            const product = products.items[current]!;
            try {
              const detail = await getProductDetail({
                apiBaseUrl,
                productId: String(product.id),
                signal: controller.signal,
              });
              if (controller.signal.aborted) return;
              nextDetails[String(detail.id)] = detail;
              scheduleFlush();
            } catch {
              if (controller.signal.aborted) return;
            }
          }
        };

        const workerCount = Math.min(PRODUCT_DETAIL_FETCH_CONCURRENCY, products.items.length);
        const workers = Array.from({ length: workerCount }, () => worker());
        await Promise.all(workers);

        if (controller.signal.aborted) return;

        setDetailsById({ ...nextDetails });
        setDetailsStatus('loaded');
      } catch (error) {
        if (controller.signal.aborted) return;
        setList({ status: 'error', message: errorMessage(error) });
      }
    })();

    return () => controller.abort();
  }, [loadToken]);

  return { list, detailsStatus, items, detailsById, reload };
}
