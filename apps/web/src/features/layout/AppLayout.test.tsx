import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../viewer/CesiumViewer', () => ({
  CesiumViewer: () => null,
}));

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function stubLegendApi(fetchMock: ReturnType<typeof vi.fn>) {
  fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString();
    if (url === '/config.json') {
      return jsonResponse({ apiBaseUrl: 'http://api.test' });
    }

    if (url === 'http://api.test/api/v1/legends?layer_type=temperature') {
      return jsonResponse({
        colors: ['#0000ff', '#ffffff', '#ff0000'],
        thresholds: [-20, 0, 40],
        labels: ['-20', '0', '40'],
      });
    }

    if (url === 'http://api.test/api/v1/legends?layer_type=wind') {
      return jsonResponse({
        colors: ['#00ff00', '#ffff00'],
        thresholds: [0, 20],
        labels: ['0', '20'],
      });
    }

    return new Response('Not Found', { status: 404 });
  });
}

describe('AppLayout', () => {
  it('persists panel collapse toggles to localStorage', async () => {
    vi.resetModules();
    localStorage.removeItem('digital-earth.layers');
    localStorage.removeItem('digital-earth.viewMode');
    localStorage.removeItem('digital-earth.layoutPanels');

    const fetchMock = vi.fn();
    stubLegendApi(fetchMock);
    vi.stubGlobal('fetch', fetchMock);

    const { AppLayout } = await import('./AppLayout');
    render(<AppLayout />);

    fireEvent.click(screen.getByRole('button', { name: '折叠时间轴' }));
    expect(screen.getByRole('button', { name: '展开时间轴' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '折叠图层树' }));
    expect(screen.getByRole('button', { name: '展开图层树' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '折叠信息面板' }));
    expect(screen.getByRole('button', { name: '展开信息面板' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '折叠图例' }));
    expect(screen.getByRole('button', { name: '展开图例' })).toBeInTheDocument();

    const persisted = JSON.parse(
      localStorage.getItem('digital-earth.layoutPanels') ?? 'null',
    ) as Record<string, unknown>;
    expect(persisted.timelineCollapsed).toBe(true);
    expect(persisted.layerTreeCollapsed).toBe(true);
    expect(persisted.infoPanelCollapsed).toBe(true);
    expect(persisted.legendCollapsed).toBe(true);
  });

  it('selects a layer via viewMode and updates legend + info panel', async () => {
    vi.resetModules();
    localStorage.removeItem('digital-earth.layers');
    localStorage.removeItem('digital-earth.viewMode');
    localStorage.removeItem('digital-earth.layoutPanels');

    const fetchMock = vi.fn();
    stubLegendApi(fetchMock);
    vi.stubGlobal('fetch', fetchMock);

    const { AppLayout } = await import('./AppLayout');
    render(<AppLayout />);

    expect(await screen.findByText('温度')).toBeInTheDocument();

    const windRow = screen.getByRole('button', { name: /wind/i });
    fireEvent.click(windRow);

    expect(await screen.findByText('图层 (wind)')).toBeInTheDocument();
    expect((await screen.findAllByText('风速')).length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText('透明度 wind'), { target: { value: '50' } });
    expect(screen.getAllByText('50%').length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: '预报' }));
    expect(screen.getByText('该视图尚未实现。')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '返回上一视图' }));
    expect(await screen.findByText('全局')).toBeInTheDocument();

    expect(fetchMock).toHaveBeenCalledWith(
      'http://api.test/api/v1/legends?layer_type=wind',
      expect.any(Object),
    );
  });
});
