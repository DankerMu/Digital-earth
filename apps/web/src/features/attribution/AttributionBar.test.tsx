import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AttributionBar } from './AttributionBar';

const SAMPLE_TEXT = [
  'Attribution (v1.0.0)',
  'Updated: 2026-01-16',
  '',
  'Sources:',
  '- © Cesium — CesiumJS (Cesium GS, Inc. · https://cesium.com/cesiumjs/ · Apache-2.0)',
  '- © ECMWF — ECMWF (European Centre for Medium-Range Weather Forecasts · https://www.ecmwf.int/ · ECMWF Terms of Use)',
  '',
  'Disclaimer:',
  '- 本平台数据仅供参考。',
  '',
].join('\n');

function mockAttributionOk() {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(SAMPLE_TEXT, {
        status: 200,
        headers: {
          ETag: '"sha256-abc"',
          'X-Attribution-Version': '1.0.0',
        },
      })
    )
  );
}

describe('AttributionBar', () => {
  it('renders entry buttons and summary', async () => {
    mockAttributionOk();
    render(<AttributionBar apiBaseUrl="http://api.example" />);

    expect(screen.getByRole('button', { name: '查看数据来源' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '查看免责声明' })).toBeInTheDocument();

    expect(await screen.findByText('© Cesium · © ECMWF')).toBeInTheDocument();
  });

  it('opens sources modal and supports copy', async () => {
    mockAttributionOk();

    const user = userEvent.setup();
    render(<AttributionBar apiBaseUrl="http://api.example" />);

    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });

    await user.click(screen.getByRole('button', { name: '查看数据来源' }));

    expect(
      await screen.findByRole('dialog', { name: '数据来源' })
    ).toBeInTheDocument();
    expect(screen.getByText(/CesiumJS/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '复制归因信息' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(SAMPLE_TEXT));
  });

  it('shows error state and retries', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(new Response('nope', { status: 500 }))
        .mockResolvedValueOnce(
          new Response(SAMPLE_TEXT, {
            status: 200,
            headers: { ETag: '"sha256-abc"', 'X-Attribution-Version': '1.0.0' },
          })
        )
    );

    const user = userEvent.setup();
    render(<AttributionBar apiBaseUrl="http://api.example" />);

    await user.click(screen.getByRole('button', { name: '查看数据来源' }));
    expect(
      await screen.findByText(/加载失败：Failed to fetch attribution: 500/)
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText(/CesiumJS/)).toBeInTheDocument();
  });
});

