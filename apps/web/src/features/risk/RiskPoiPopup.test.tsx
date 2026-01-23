import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { RiskPoiPopup } from './RiskPoiPopup';

describe('RiskPoiPopup', () => {
  it('renders loading state and supports actions', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onOpenDisasterDemo = vi.fn();

    render(
      <RiskPoiPopup
        poi={{
          id: 1,
          name: 'poi-a',
          type: 'fire',
          lon: 120,
          lat: 30,
          alt: null,
          weight: 1,
          tags: null,
          risk_level: 'unknown',
        }}
        evaluation={null}
        status="loading"
        errorMessage={null}
        onClose={onClose}
        onOpenDisasterDemo={onOpenDisasterDemo}
      />,
    );

    expect(screen.getByLabelText('Risk POI details')).toHaveTextContent('poi-a');
    expect(screen.getByLabelText('Risk details loading')).toHaveTextContent('加载中');

    await user.click(screen.getByRole('button', { name: '查看灾害演示' }));
    expect(onOpenDisasterDemo).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: 'Close risk popup' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('renders an error message', () => {
    render(
      <RiskPoiPopup
        poi={{
          id: 1,
          name: 'poi-a',
          type: 'fire',
          lon: 120,
          lat: 30,
          alt: null,
          weight: 1,
          tags: null,
          risk_level: 'unknown',
        }}
        evaluation={null}
        status="error"
        errorMessage="boom"
        onClose={() => {}}
        onOpenDisasterDemo={() => {}}
      />,
    );

    expect(screen.getByLabelText('Risk details error')).toHaveTextContent('boom');
  });

  it('renders reasons and factors when loaded', () => {
    render(
      <RiskPoiPopup
        poi={{
          id: 1,
          name: 'poi-a',
          type: 'fire',
          lon: 120,
          lat: 30,
          alt: null,
          weight: 1,
          tags: null,
          risk_level: 2,
        }}
        evaluation={{
          poi_id: 1,
          level: 4,
          score: 0.9,
          factors: [
            {
              id: 'wind',
              value: 8.1,
              score: 0.7,
              weight: 1,
              normalized_weight: 1,
              contribution: 0.5,
            },
          ],
          reasons: [
            {
              factor_id: 'wind',
              factor_name: 'Wind',
              value: 8.1,
              threshold: 5,
              contribution: 0.5,
            },
          ],
        }}
        status="loaded"
        errorMessage={null}
        onClose={() => {}}
        onOpenDisasterDemo={() => {}}
      />,
    );

    expect(screen.getByLabelText('Risk POI details')).toHaveTextContent('L4');
    expect(screen.getByText('Wind')).toBeInTheDocument();
    expect(screen.getAllByText('8.10')).toHaveLength(2);
    expect(screen.getByText('5.00')).toBeInTheDocument();
    expect(screen.getByText('wind')).toBeInTheDocument();
    expect(screen.getByText('0.500')).toBeInTheDocument();
  });
});
