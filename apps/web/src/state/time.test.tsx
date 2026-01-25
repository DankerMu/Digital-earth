import { act, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import {
  DEFAULT_LEVEL_KEY,
  DEFAULT_RUN_TIME_KEY,
  DEFAULT_TIME_KEY,
  DEFAULT_VALID_TIME_KEY,
  useTimeStore,
} from './time';

function Harness() {
  const timeKey = useTimeStore((state) => state.timeKey);
  return <div data-testid="timeKey">{timeKey}</div>;
}

describe('useTimeStore', () => {
  beforeEach(() => {
    useTimeStore.setState({
      runTimeKey: DEFAULT_RUN_TIME_KEY,
      validTimeKey: DEFAULT_VALID_TIME_KEY,
      levelKey: DEFAULT_LEVEL_KEY,
    });
  });

  it('defaults validTimeKey to +3h', () => {
    const state = useTimeStore.getState();
    expect(state.runTimeKey).toBe(DEFAULT_RUN_TIME_KEY);
    expect(state.validTimeKey).toBe(DEFAULT_VALID_TIME_KEY);
    expect(state.levelKey).toBe(DEFAULT_LEVEL_KEY);
    expect(state.timeKey).toBe(DEFAULT_TIME_KEY);
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
