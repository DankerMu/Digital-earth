import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { DisclaimerLauncher } from './DisclaimerLauncher';

describe('DisclaimerLauncher', () => {
  it('renders entry button and opens/closes dialog', async () => {
    const user = userEvent.setup();
    render(<DisclaimerLauncher />);

    expect(
      screen.getByRole('button', { name: '打开数据来源与免责声明' })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('dialog', { name: '数据来源与免责声明' })
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '打开数据来源与免责声明' }));

    expect(
      await screen.findByRole('dialog', { name: '数据来源与免责声明' })
    ).toBeInTheDocument();

    expect(screen.getByText('ECMWF（气象数据）')).toBeInTheDocument();
    expect(screen.getByText('CLDAS（监测/陆面数据）')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Cesium ion' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'NASA GIBS' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'EOX' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '关闭弹窗' }));
    await waitFor(() =>
      expect(
        screen.queryByRole('dialog', { name: '数据来源与免责声明' })
      ).not.toBeInTheDocument()
    );
  });

  it('closes via Escape key', async () => {
    const user = userEvent.setup();
    render(<DisclaimerLauncher />);

    await user.click(screen.getByRole('button', { name: '打开数据来源与免责声明' }));
    await screen.findByRole('dialog', { name: '数据来源与免责声明' });

    await user.keyboard('{Escape}');
    await waitFor(() =>
      expect(
        screen.queryByRole('dialog', { name: '数据来源与免责声明' })
      ).not.toBeInTheDocument()
    );
  });
});
