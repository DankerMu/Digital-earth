import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { SamplingCard } from './SamplingCard';
import type { SamplingCardState } from './useSamplingCard';

describe('SamplingCard', () => {
  it('does not render when closed', () => {
    const state: SamplingCardState = {
      isOpen: false,
      status: 'idle',
      location: null,
      data: null,
      errorMessage: null,
    };

    render(<SamplingCard state={state} onClose={() => {}} />);

    expect(screen.queryByLabelText('Sampling data')).not.toBeInTheDocument();
  });

  it('renders loading and can be closed', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const state: SamplingCardState = {
      isOpen: true,
      status: 'loading',
      location: { lon: 116.391, lat: 39.9075 },
      data: null,
      errorMessage: null,
    };

    render(<SamplingCard state={state} onClose={onClose} />);

    expect(screen.getByLabelText('Sampling data')).toBeInTheDocument();
    expect(screen.getByLabelText('Sampling loading')).toBeInTheDocument();
    expect(screen.getByText('39.9075, 116.3910')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Close sampling card' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('renders sampled values and shows placeholders for missing values', () => {
    const state: SamplingCardState = {
      isOpen: true,
      status: 'loaded',
      location: { lon: 120, lat: 30 },
      data: {
        temperatureC: 5,
        windSpeedMps: 2.5,
        windDirectionDeg: 143.13,
        precipitationMm: null,
        cloudCoverPercent: 33.3,
      },
      errorMessage: null,
    };

    render(<SamplingCard state={state} onClose={() => {}} />);

    expect(screen.getByText('5.0')).toBeInTheDocument();
    expect(screen.getByText(/2\.5/)).toBeInTheDocument();
    expect(screen.getByText(/143°/)).toBeInTheDocument();
    expect(screen.getAllByText('--').length).toBeGreaterThan(0);
    expect(screen.getByText('33')).toBeInTheDocument();
  });
});
