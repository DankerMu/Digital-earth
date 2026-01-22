import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { DisclaimerLauncher } from './DisclaimerLauncher';

describe('DisclaimerLauncher', () => {
  it('renders entry button and opens/closes dialog', async () => {
    const user = userEvent.setup();
    render(<DisclaimerLauncher />);

    const triggerButton = screen.getByRole('button', { name: '打开数据来源与免责声明' });
    expect(triggerButton).toBeInTheDocument();
    expect(triggerButton).toHaveAttribute('aria-haspopup', 'dialog');
    expect(triggerButton).toHaveAttribute('aria-expanded', 'false');
    expect(
      screen.queryByRole('dialog', { name: '数据来源与免责声明' })
    ).not.toBeInTheDocument();

    await user.click(triggerButton);

    expect(triggerButton).toHaveAttribute('aria-expanded', 'true');
    expect(
      await screen.findByRole('dialog', { name: '数据来源与免责声明' })
    ).toBeInTheDocument();

    expect(screen.getByText('归因信息与版权声明')).toBeInTheDocument();

    expect(screen.getByText('ECMWF（气象数据）')).toBeInTheDocument();
    expect(screen.getByText('CLDAS（监测/陆面数据）')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Cesium ion' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'NASA GIBS' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'EOX' })).toBeInTheDocument();

    const closeButton = await screen.findByRole('button', { name: '关闭弹窗' });
    await waitFor(() => expect(closeButton).toHaveFocus());

    await user.click(closeButton);
    await waitFor(() =>
      expect(
        screen.queryByRole('dialog', { name: '数据来源与免责声明' })
      ).not.toBeInTheDocument()
    );

    expect(triggerButton).toHaveAttribute('aria-expanded', 'false');
    await waitFor(() => expect(triggerButton).toHaveFocus());
  });

  it('closes via Escape key', async () => {
    const user = userEvent.setup();
    render(<DisclaimerLauncher />);

    const triggerButton = screen.getByRole('button', { name: '打开数据来源与免责声明' });
    await user.click(triggerButton);
    await screen.findByRole('dialog', { name: '数据来源与免责声明' });

    await user.keyboard('{Escape}');
    await waitFor(() =>
      expect(
        screen.queryByRole('dialog', { name: '数据来源与免责声明' })
      ).not.toBeInTheDocument()
    );

    await waitFor(() => expect(triggerButton).toHaveFocus());
  });

  it('supports localized UI strings', async () => {
    const user = userEvent.setup();
    render(<DisclaimerLauncher locale="en" />);

    const triggerButton = screen.getByRole('button', { name: 'Open Data Sources & Disclaimer' });
    expect(triggerButton).toHaveAttribute('aria-haspopup', 'dialog');
    expect(triggerButton).toHaveAttribute('aria-expanded', 'false');

    await user.click(triggerButton);

    expect(
      await screen.findByRole('dialog', { name: 'Data Sources & Disclaimer' })
    ).toBeInTheDocument();
    expect(screen.getByText('Attribution and copyright notice')).toBeInTheDocument();

    const closeButton = await screen.findByRole('button', { name: 'Close dialog' });
    expect(closeButton).toHaveTextContent('Close');
  });
});
