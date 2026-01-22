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

  it('does not start playing if loadFrame fails', async () => {
    const deferred = createDeferred<void>();
    const loadFrame = vi.fn().mockReturnValue(deferred.promise);
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});

    render(
      <TimeController frames={makeFrames()} initialIndex={2} loadFrame={loadFrame} />,
    );

    fireEvent.click(screen.getByRole('button', { name: '播放' }));

    expect(screen.getByText('2024-01-15 12:00')).toBeInTheDocument();
    expect(loadFrame).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText('加载中')).toBeInTheDocument();

    deferred.reject(new Error('load failed'));

    await waitFor(() => {
      expect(screen.queryByLabelText('加载中')).not.toBeInTheDocument();
    });

    expect(screen.getByRole('button', { name: '播放' })).toBeInTheDocument();
    expect(consoleError).toHaveBeenCalledWith('[TimeController] loadFrame failed', expect.any(Error));
    consoleError.mockRestore();
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

  it('refreshes and loads immediately on slider click', async () => {
    const onRefreshLayers = vi.fn();
    const loadFrame = vi.fn(async () => undefined);

    render(
      <TimeController
        frames={makeFrames()}
        onRefreshLayers={onRefreshLayers}
        loadFrame={loadFrame}
        dragDebounceMs={400}
      />,
    );

    const slider = screen.getByLabelText('时间轴');

    fireEvent.change(slider, { target: { value: '1' } });

    expect(onRefreshLayers).toHaveBeenCalledTimes(1);
    expect(onRefreshLayers).toHaveBeenLastCalledWith(expect.any(Date), 1);
    expect(loadFrame).toHaveBeenCalledTimes(1);
    expect(loadFrame).toHaveBeenLastCalledWith(expect.any(Date), 1, expect.any(Object));
  });

  it('debounces refresh and loadFrame while dragging the timeline slider', async () => {
    vi.useFakeTimers();

    const onRefreshLayers = vi.fn();
    const loadFrame = vi.fn(async () => undefined);

    render(
      <TimeController
        frames={makeFrames()}
        onRefreshLayers={onRefreshLayers}
        loadFrame={loadFrame}
        dragDebounceMs={400}
      />,
    );

    const slider = screen.getByLabelText('时间轴');

    fireEvent.pointerDown(slider, { pointerId: 1 });
    fireEvent.pointerMove(slider, { pointerId: 1 });
    fireEvent.change(slider, { target: { value: '1' } });
    fireEvent.change(slider, { target: { value: '2' } });

    await act(async () => {});
    expect(screen.getByLabelText('加载中')).toBeInTheDocument();

    expect(onRefreshLayers).not.toHaveBeenCalled();
    expect(loadFrame).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(399);
    });

    expect(onRefreshLayers).not.toHaveBeenCalled();
    expect(loadFrame).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });

    expect(onRefreshLayers).toHaveBeenCalledTimes(1);
    expect(onRefreshLayers).toHaveBeenLastCalledWith(expect.any(Date), 2);
    expect(loadFrame).toHaveBeenCalledTimes(1);
    expect(loadFrame).toHaveBeenLastCalledWith(expect.any(Date), 2, expect.any(Object));

    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByLabelText('加载中')).not.toBeInTheDocument();

    vi.useRealTimers();
  });

  it('reports non-abort loadFrame errors during drag debounce', async () => {
    vi.useFakeTimers();

    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    const loadFrame = vi.fn().mockRejectedValue(new Error('load failed'));

    render(<TimeController frames={makeFrames()} loadFrame={loadFrame} dragDebounceMs={400} />);

    const slider = screen.getByLabelText('时间轴');
    fireEvent.pointerDown(slider, { pointerId: 1 });
    fireEvent.pointerMove(slider, { pointerId: 1 });
    fireEvent.change(slider, { target: { value: '1' } });

    await act(async () => {});
    expect(screen.getByLabelText('加载中')).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });

    await act(async () => {
      await Promise.resolve();
    });

    expect(loadFrame).toHaveBeenCalledTimes(1);
    expect(consoleError).toHaveBeenCalledWith(
      '[TimeController] loadFrame failed',
      expect.any(Error),
    );
    expect(screen.queryByLabelText('加载中')).not.toBeInTheDocument();

    consoleError.mockRestore();
    vi.useRealTimers();
  });

  it('cancels pending debounced work when frames change', async () => {
    vi.useFakeTimers();

    const onRefreshLayers = vi.fn();
    const loadFrame = vi.fn(async () => undefined);

    const { rerender } = render(
      <TimeController
        frames={makeFrames()}
        onRefreshLayers={onRefreshLayers}
        loadFrame={loadFrame}
        dragDebounceMs={400}
      />,
    );

    const slider = screen.getByLabelText('时间轴');
    fireEvent.pointerDown(slider, { pointerId: 1 });
    fireEvent.pointerMove(slider, { pointerId: 1 });
    fireEvent.change(slider, { target: { value: '2' } });

    await act(async () => {});
    expect(screen.getByLabelText('加载中')).toBeInTheDocument();

    rerender(
      <TimeController
        frames={[
          new Date('2024-01-15T15:00:00Z'),
          new Date('2024-01-15T16:00:00Z'),
          new Date('2024-01-15T17:00:00Z')
        ]}
        onRefreshLayers={onRefreshLayers}
        loadFrame={loadFrame}
        dragDebounceMs={400}
      />,
    );

    await act(async () => {});
    expect(screen.queryByLabelText('加载中')).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });

    expect(onRefreshLayers).not.toHaveBeenCalled();
    expect(loadFrame).not.toHaveBeenCalled();

    vi.useRealTimers();
  });

  it('aborts the previous loadFrame request when a new drag is scheduled', async () => {
    vi.useFakeTimers();

    const deferred1 = createDeferred<void>();
    const deferred2 = createDeferred<void>();
    const signals: AbortSignal[] = [];

    const loadFrame = vi
      .fn()
      .mockImplementationOnce((_: Date, __: number, options?: { signal?: AbortSignal }) => {
        const signal = options?.signal;
        if (signal) {
          signals.push(signal);
          signal.addEventListener('abort', () => {
            deferred1.reject(new DOMException('Aborted', 'AbortError'));
          });
        }
        return deferred1.promise;
      })
      .mockImplementationOnce((_: Date, __: number, options?: { signal?: AbortSignal }) => {
        const signal = options?.signal;
        if (signal) {
          signals.push(signal);
          signal.addEventListener('abort', () => {
            deferred2.reject(new DOMException('Aborted', 'AbortError'));
          });
        }
        return deferred2.promise;
      });

    render(<TimeController frames={makeFrames()} loadFrame={loadFrame} dragDebounceMs={400} />);

    const slider = screen.getByLabelText('时间轴');
    fireEvent.pointerDown(slider, { pointerId: 1 });
    fireEvent.pointerMove(slider, { pointerId: 1 });
    fireEvent.change(slider, { target: { value: '1' } });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });

    expect(loadFrame).toHaveBeenCalledTimes(1);
    expect(signals[0]?.aborted).toBe(false);

    fireEvent.change(slider, { target: { value: '2' } });
    expect(signals[0]?.aborted).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });

    expect(loadFrame).toHaveBeenCalledTimes(2);

    deferred2.resolve();

    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByLabelText('加载中')).not.toBeInTheDocument();

    vi.useRealTimers();
  });
});
