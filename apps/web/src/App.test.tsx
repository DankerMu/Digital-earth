import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

import App from './App';

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

it('switches primary layer and updates legend', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
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

  vi.stubGlobal('fetch', fetchMock);

  render(<App />);

  expect(await screen.findByText('温度')).toBeInTheDocument();

  const windCheckbox = screen.getByRole('checkbox', { name: 'wind' });
  fireEvent.click(windCheckbox);

  const primarySelect = screen.getByRole('combobox', { name: 'Primary' });
  fireEvent.change(primarySelect, { target: { value: 'wind' } });

  expect(await screen.findByText('风速')).toBeInTheDocument();

  expect(fetchMock).toHaveBeenCalledWith(
    'http://api.test/api/v1/legends?layer_type=wind',
    expect.any(Object),
  );
});
