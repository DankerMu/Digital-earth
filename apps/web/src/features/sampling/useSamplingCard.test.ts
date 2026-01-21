import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { useSamplingCard } from './useSamplingCard';

describe('useSamplingCard', () => {
  it('opens, updates, and closes the sampling card', () => {
    const { result } = renderHook(() => useSamplingCard());

    expect(result.current.state.isOpen).toBe(false);
    expect(result.current.state.status).toBe('idle');

    act(() => {
      result.current.setData({
        temperatureC: 1,
        windSpeedMps: 2,
        windDirectionDeg: 3,
        precipitationMm: 4,
        cloudCoverPercent: 5,
      });
    });

    expect(result.current.state.isOpen).toBe(false);

    act(() => {
      result.current.open({ lon: 120, lat: 30 });
    });

    expect(result.current.state.isOpen).toBe(true);
    expect(result.current.state.status).toBe('loading');
    expect(result.current.state.location).toEqual({ lon: 120, lat: 30 });

    act(() => {
      result.current.setData({
        temperatureC: 1,
        windSpeedMps: 2,
        windDirectionDeg: 3,
        precipitationMm: 4,
        cloudCoverPercent: 5,
      });
    });

    expect(result.current.state.status).toBe('loaded');
    expect(result.current.state.data).toEqual({
      temperatureC: 1,
      windSpeedMps: 2,
      windDirectionDeg: 3,
      precipitationMm: 4,
      cloudCoverPercent: 5,
    });

    act(() => {
      result.current.setError('oops');
    });

    expect(result.current.state.status).toBe('error');
    expect(result.current.state.errorMessage).toBe('oops');
    expect(result.current.state.data).toBeNull();

    act(() => {
      result.current.close();
    });

    expect(result.current.state.isOpen).toBe(false);
    expect(result.current.state.status).toBe('idle');
    expect(result.current.state.location).toBeNull();
    expect(result.current.state.data).toBeNull();
  });
});
