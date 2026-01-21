import { useCallback, useState } from 'react';

export type SamplingLocation = {
  lon: number;
  lat: number;
};

export type SamplingData = {
  temperatureC: number | null;
  windSpeedMps: number | null;
  windDirectionDeg: number | null;
  precipitationMm: number | null;
  cloudCoverPercent: number | null;
};

export type SamplingCardState = {
  isOpen: boolean;
  status: 'idle' | 'loading' | 'loaded' | 'error';
  location: SamplingLocation | null;
  data: SamplingData | null;
  errorMessage: string | null;
};

const INITIAL_STATE: SamplingCardState = {
  isOpen: false,
  status: 'idle',
  location: null,
  data: null,
  errorMessage: null,
};

export function useSamplingCard() {
  const [state, setState] = useState<SamplingCardState>(INITIAL_STATE);

  const open = useCallback((location: SamplingLocation) => {
    setState({
      isOpen: true,
      status: 'loading',
      location,
      data: null,
      errorMessage: null,
    });
  }, []);

  const close = useCallback(() => {
    setState(INITIAL_STATE);
  }, []);

  const setData = useCallback((data: SamplingData) => {
    setState((prev) => {
      if (!prev.isOpen) return prev;
      return {
        ...prev,
        status: 'loaded',
        data,
        errorMessage: null,
      };
    });
  }, []);

  const setError = useCallback((message: string) => {
    setState((prev) => {
      if (!prev.isOpen) return prev;
      return {
        ...prev,
        status: 'error',
        data: null,
        errorMessage: message,
      };
    });
  }, []);

  return {
    state,
    open,
    close,
    setData,
    setError,
  };
}

