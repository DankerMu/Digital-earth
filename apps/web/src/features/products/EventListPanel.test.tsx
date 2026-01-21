import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { clearConfigCache } from '../../config';
import { useViewModeStore } from '../../state/viewMode';
import { clearProductsCache } from './productsApi';
import { EventListPanel } from './EventListPanel';

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

describe('EventListPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    clearConfigCache();
    clearProductsCache();
    localStorage.removeItem('digital-earth.viewMode');
    useViewModeStore.setState({ route: { viewModeId: 'global' }, history: [], saved: {} });
  });

  it('loads products and enters event mode on click', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url =
          typeof input === 'string'
            ? input
            : input instanceof URL
              ? input.toString()
              : input.url;

        if (url.endsWith('/config.json')) {
          return jsonResponse({ apiBaseUrl: 'http://api.test' });
        }

        if (url === 'http://api.test/api/v1/products') {
          return jsonResponse({
            page: 1,
            page_size: 50,
            total: 1,
            items: [
              {
                id: 1,
                title: '降雪',
                hazards: [
                  {
                    severity: 'low',
                    geometry: { type: 'Polygon', coordinates: [] },
                    bbox: { min_x: 0, min_y: 0, max_x: 1, max_y: 1 },
                  },
                ],
              },
            ],
          });
        }

        if (url === 'http://api.test/api/v1/products/1') {
          return jsonResponse({
            id: 1,
            title: '降雪',
            text: '降雪预警',
            issued_at: '2026-01-01T00:00:00Z',
            valid_from: '2026-01-01T00:00:00Z',
            valid_to: '2026-01-02T00:00:00Z',
            version: 1,
            status: 'published',
            hazards: [
              {
                id: 11,
                severity: 'low',
                geometry: { type: 'Polygon', coordinates: [] },
                bbox: { min_x: 0, min_y: 0, max_x: 1, max_y: 1 },
                valid_from: '2026-01-01T00:00:00Z',
                valid_to: '2026-01-02T00:00:00Z',
              },
            ],
          });
        }

        return jsonResponse({}, 404);
      }),
    );

    render(<EventListPanel />);

    expect(screen.getByText('Loading…')).toBeInTheDocument();

    expect(await screen.findByTestId('event-item-1')).toBeInTheDocument();
    expect(await screen.findByText('降雪预警')).toBeInTheDocument();
    expect(screen.getByText('类型: 降雪')).toBeInTheDocument();
    expect(screen.getByText('等级: 低')).toBeInTheDocument();

    await screen.findByText(
      '有效期: 2026-01-01 00:00Z ~ 2026-01-02 00:00Z',
    );

    const user = userEvent.setup();
    await user.click(screen.getByTestId('event-item-1'));

    await waitFor(() => {
      const route = useViewModeStore.getState().route;
      expect(route.viewModeId).toBe('event');
      if (route.viewModeId !== 'event') {
        throw new Error('Expected event route');
      }
      expect(route.productId).toBe('1');
    });

    expect(screen.getByTestId('event-item-1')).toHaveAttribute('aria-selected', 'true');
  });

  it('renders an error when products list fails to load', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url =
          typeof input === 'string'
            ? input
            : input instanceof URL
              ? input.toString()
              : input.url;

        if (url.endsWith('/config.json')) {
          return jsonResponse({ apiBaseUrl: 'http://api.test' });
        }

        if (url === 'http://api.test/api/v1/products') {
          return new Response('Server error', { status: 500 });
        }

        return jsonResponse({}, 404);
      }),
    );

    render(<EventListPanel />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Failed to load products: 500');
  });
});
