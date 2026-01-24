import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

vi.mock('./features/viewer/CesiumViewer', () => ({
  CesiumViewer: () => null,
}));

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

it('switches active layer and updates legend', async () => {
  localStorage.removeItem('digital-earth.layers');
  localStorage.removeItem('digital-earth.viewMode');
  localStorage.removeItem('digital-earth.layoutPanels');
  vi.resetModules();

  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString();
    if (url === '/config.json') {
      return jsonResponse({ apiBaseUrl: 'http://api.test' });
    }

    if (url === 'http://api.test/api/v1/attribution') {
      return new Response('© Cesium · © ECMWF / CLDAS', {
        status: 200,
        headers: { 'Content-Type': 'text/plain' },
      });
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

  vi.stubGlobal('fetch', fetchMock);

  const { default: App } = await import('./App');
  render(<App />);

  expect(await screen.findByText('温度')).toBeInTheDocument();
  expect(await screen.findByRole('button', { name: '查看数据来源' })).toBeInTheDocument();

  const windCheckbox = screen.getByRole('checkbox', { name: '显示 wind' });
  fireEvent.click(windCheckbox);

  expect(await screen.findByText('风速')).toBeInTheDocument();

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      'http://api.test/api/v1/legends?layer_type=wind',
      expect.any(Object),
    );
  });
});
