import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DiagnosticsPanel } from './DiagnosticsPanel';
import type { DiagnosticsSnapshot } from './types';

describe('DiagnosticsPanel', () => {
  it('renders key metrics and supports export', () => {
    const onClose = vi.fn();
    const onExport = vi.fn();

    const snapshot: DiagnosticsSnapshot = {
      enabled: true,
      fps: 60,
      memory: { usedBytes: 1024 * 1024 * 50, totalBytes: 1024 * 1024 * 100 },
      requests: {
        total: 10,
        tileTotal: 8,
        failed: 2,
        tileFailed: 1,
        cacheHits: 3,
        tileCacheHits: 2
      },
      errorsTotal: 1,
      requestLogs: [
        {
          at: 1,
          url: '/tiles/1/2/3.png',
          method: 'GET',
          ok: true,
          status: 200,
          durationMs: 10,
          isTile: true
        }
      ],
      errorLogs: [{ at: 2, message: 'boom' }]
    };

    render(<DiagnosticsPanel snapshot={snapshot} onClose={onClose} onExport={onExport} />);

    expect(screen.getByTestId('diagnostics-panel')).toBeInTheDocument();
    expect(screen.getByText('FPS')).toBeInTheDocument();
    expect(screen.getByText('Tile Requests')).toBeInTheDocument();
    expect(screen.getByText('Errors')).toBeInTheDocument();

    expect(screen.getByText('FPS').parentElement).toHaveTextContent('60');
    expect(screen.getByText('Tile Requests').parentElement).toHaveTextContent('8');
    expect(screen.getByText('Errors').parentElement).toHaveTextContent('1');
    expect(screen.getByText('Tile Cache Hit').parentElement).toHaveTextContent('2/8');

    fireEvent.click(screen.getByRole('button', { name: /export/i }));
    expect(onExport).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
