import { act, render, screen } from '@testing-library/react';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';

import { useViewerStatsStore } from './viewerStats';

describe('viewerStats store', () => {
  it('defaults to null fps', () => {
    useViewerStatsStore.setState({ fps: null });
    expect(useViewerStatsStore.getState().fps).toBeNull();
  });

  it('setFps updates the store', () => {
    useViewerStatsStore.getState().setFps(55);
    expect(useViewerStatsStore.getState().fps).toBe(55);
  });

  it('setState supports partial updates and normalizes invalid values', () => {
    useViewerStatsStore.setState({ fps: 42 });
    expect(useViewerStatsStore.getState().fps).toBe(42);

    useViewerStatsStore.setState({ fps: Number.NaN });
    expect(useViewerStatsStore.getState().fps).toBeNull();
  });

  it('subscribes via useSyncExternalStore', () => {
    useViewerStatsStore.setState({ fps: null });

    function FpsLabel() {
      const fps = useViewerStatsStore((state) => state.fps);
      return createElement('div', { 'data-testid': 'fps' }, fps == null ? 'N/A' : String(fps));
    }

    render(createElement(FpsLabel));
    expect(screen.getByTestId('fps')).toHaveTextContent('N/A');

    act(() => {
      useViewerStatsStore.getState().setFps(60);
    });
    expect(screen.getByTestId('fps')).toHaveTextContent('60');
  });
});

