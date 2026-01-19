import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { LegendPanel, type LayerSelection } from './LegendPanel';

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('LegendPanel', () => {
  it('loads legend for primary layer and updates when primary changes', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url === '/config.json') {
        return jsonResponse({ apiBaseUrl: 'http://api.test' });
      }

      const layerType = new URL(url).searchParams.get('layer_type');

      if (layerType === 'temperature') {
        return jsonResponse({
          colors: ['#0000ff', '#ffffff', '#ff0000'],
          thresholds: [-20, 0, 40],
          labels: ['-20', '0', '40'],
        });
      }

      if (layerType === 'wind') {
        return jsonResponse({
          colors: ['#00ff00', '#ffff00'],
          thresholds: [0, 20],
          labels: ['0', '20'],
        });
      }

      return new Response('Not Found', { status: 404 });
    });

    vi.stubGlobal('fetch', fetchMock);

    const layers: LayerSelection[] = [
      { id: 'temperature', type: 'temperature', isVisible: true, isPrimary: true },
      { id: 'wind', type: 'wind', isVisible: true },
    ];

    const { rerender } = render(<LegendPanel layers={layers} />);

    expect(await screen.findByText('温度')).toBeInTheDocument();
    expect(screen.getByText('°C')).toBeInTheDocument();

    expect(fetchMock).toHaveBeenCalledWith(
      'http://api.test/api/v1/legends?layer_type=temperature',
      expect.any(Object),
    );

    rerender(
      <LegendPanel
        layers={[
          { id: 'temperature', type: 'temperature', isVisible: true },
          { id: 'wind', type: 'wind', isVisible: true, isPrimary: true },
        ]}
      />,
    );

    expect(await screen.findByText('风速')).toBeInTheDocument();
    expect(screen.getByText('m/s')).toBeInTheDocument();

    expect(fetchMock).toHaveBeenCalledWith(
      'http://api.test/api/v1/legends?layer_type=wind',
      expect.any(Object),
    );
  });

  it('positions tick labels at threshold percents (no off-by-one)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString();
        if (url === '/config.json') {
          return jsonResponse({ apiBaseUrl: 'http://api.test' });
        }

        return jsonResponse({
          colors: ['#0000ff', '#ffffff', '#ff0000'],
          thresholds: [-20, 0, 40],
          labels: ['-20', '0', '40'],
        });
      }),
    );

    render(
      <LegendPanel
        layers={[{ id: 'temperature', type: 'temperature', isVisible: true }]}
      />,
    );

    await screen.findByTestId('legend-gradient');

    expect(screen.getByTestId('legend-tick-0')).toHaveStyle({
      left: '0.00%',
      transform: 'translateX(0)',
    });

    expect(screen.getByTestId('legend-tick-1')).toHaveStyle({
      left: '33.33%',
      transform: 'translateX(-50%)',
    });

    expect(screen.getByTestId('legend-tick-2')).toHaveStyle({
      left: '100.00%',
      transform: 'translateX(-100%)',
    });
  });
});
