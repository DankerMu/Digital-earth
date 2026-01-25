import { act, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { DEFAULT_TIME_KEY, useTimeStore } from './time';

function Harness() {
  const timeKey = useTimeStore((state) => state.timeKey);
  return <div data-testid="timeKey">{timeKey}</div>;
}

describe('useTimeStore', () => {
  beforeEach(() => {
    useTimeStore.setState({ timeKey: DEFAULT_TIME_KEY });
  });

  it('updates subscribers when timeKey changes', () => {
    render(<Harness />);
    expect(screen.getByTestId('timeKey')).toHaveTextContent(DEFAULT_TIME_KEY);

    act(() => {
      useTimeStore.getState().setTimeKey(' 2025-12-22T01:00:00Z ');
    });

    expect(screen.getByTestId('timeKey')).toHaveTextContent('2025-12-22T01:00:00Z');
  });

  it('ignores empty timeKey updates', () => {
    act(() => {
      useTimeStore.getState().setTimeKey('   ');
    });

    expect(useTimeStore.getState().timeKey).toBe(DEFAULT_TIME_KEY);
  });
});
