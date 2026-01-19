import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { TimeController } from './TimeController';

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function makeFrames() {
  return [
    new Date('2024-01-15T12:00:00Z'),
    new Date('2024-01-15T13:00:00Z'),
    new Date('2024-01-15T14:00:00Z')
  ];
}

describe('TimeController', () => {
  it('steps frames and refreshes layers', async () => {
    const onTimeChange = vi.fn();
    const onRefreshLayers = vi.fn();

    render(
      <TimeController
        frames={makeFrames()}
        onTimeChange={onTimeChange}
        onRefreshLayers={onRefreshLayers}
      />,
    );

    expect(screen.getByText('2024-01-15 12:00')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '下一帧' }));

    expect(screen.getByText('2024-01-15 13:00')).toBeInTheDocument();
    expect(onTimeChange).toHaveBeenCalledTimes(1);
    expect(onRefreshLayers).toHaveBeenCalledTimes(1);
  });

  it('jumps via the timeline slider', async () => {
    const onTimeChange = vi.fn();

    render(<TimeController frames={makeFrames()} onTimeChange={onTimeChange} />);

    const slider = screen.getByLabelText('时间轴');
    fireEvent.change(slider, { target: { value: '2' } });

    await waitFor(() => {
      expect(onTimeChange).toHaveBeenCalledWith(expect.any(Date), 2);
    });
  });

  it('shows loading indicator while buffering', async () => {
    const deferred = createDeferred<void>();
    const loadFrame = vi.fn().mockReturnValue(deferred.promise);

    render(<TimeController frames={makeFrames()} loadFrame={loadFrame} />);

    fireEvent.click(screen.getByRole('button', { name: '下一帧' }));
    expect(loadFrame).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText('加载中')).toBeInTheDocument();

    deferred.resolve();

    await waitFor(() => {
      expect(screen.queryByLabelText('加载中')).not.toBeInTheDocument();
    });
  });

  it('plays smoothly and respects speed', async () => {
    vi.useFakeTimers();
    const onTimeChange = vi.fn();

    render(
      <TimeController
        frames={makeFrames()}
        baseIntervalMs={1000}
        onTimeChange={onTimeChange}
      />,
    );

    act(() => {
      fireEvent.click(screen.getByRole('button', { name: '播放' }));
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(onTimeChange).toHaveBeenCalledTimes(1);
    expect(screen.getByText('2024-01-15 13:00')).toBeInTheDocument();

    act(() => {
      fireEvent.change(screen.getByLabelText('播放速度'), {
        target: { value: '2' }
      });
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(onTimeChange).toHaveBeenCalledTimes(2);
    expect(screen.getByText('2024-01-15 14:00')).toBeInTheDocument();

    vi.useRealTimers();
  });
});
