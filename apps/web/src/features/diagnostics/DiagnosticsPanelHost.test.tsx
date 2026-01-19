import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DiagnosticsPanelHost } from './DiagnosticsPanelHost';

describe('DiagnosticsPanelHost', () => {
  const originalFetch = globalThis.fetch;
  const originalRaf = globalThis.requestAnimationFrame;
  const originalCaf = globalThis.cancelAnimationFrame;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    globalThis.requestAnimationFrame = originalRaf;
    globalThis.cancelAnimationFrame = originalCaf;
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('toggles panel via Ctrl+Shift+D', () => {
    globalThis.requestAnimationFrame = () => 1;
    globalThis.cancelAnimationFrame = vi.fn();
    globalThis.fetch = vi.fn(
      async () => new Response('ok', { status: 200 })
    ) as unknown as typeof fetch;

    render(<DiagnosticsPanelHost />);
    expect(screen.queryByTestId('diagnostics-panel')).not.toBeInTheDocument();

    fireEvent.keyDown(window, { ctrlKey: true, shiftKey: true, code: 'KeyD' });
    expect(screen.getByTestId('diagnostics-panel')).toBeInTheDocument();

    fireEvent.keyDown(window, { ctrlKey: true, shiftKey: true, code: 'KeyD' });
    expect(screen.queryByTestId('diagnostics-panel')).not.toBeInTheDocument();
  });

  it('exports diagnostics as json download', () => {
    globalThis.requestAnimationFrame = () => 1;
    globalThis.cancelAnimationFrame = vi.fn();
    globalThis.fetch = vi.fn(
      async () => new Response('ok', { status: 200 })
    ) as unknown as typeof fetch;

    const createObjectURL = vi.fn(() => 'blob:mock');
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', {
      value: createObjectURL,
      configurable: true
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      value: revokeObjectURL,
      configurable: true
    });

    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});
    vi.useFakeTimers();

    render(<DiagnosticsPanelHost />);
    fireEvent.keyDown(window, { ctrlKey: true, shiftKey: true, code: 'KeyD' });

    fireEvent.click(screen.getByRole('button', { name: /export/i }));

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(anchorClick).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(0);
    expect(revokeObjectURL).toHaveBeenCalledTimes(1);
  });
});
