import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { HelpLauncher } from './HelpLauncher';

describe('HelpLauncher', () => {
  it('renders entry button and opens/closes dialog', async () => {
    const user = userEvent.setup();
    render(<HelpLauncher />);

    const triggerButton = screen.getByRole('button', { name: '打开用户帮助' });
    expect(triggerButton).toBeInTheDocument();
    expect(triggerButton).toHaveAttribute('aria-haspopup', 'dialog');
    expect(triggerButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('dialog', { name: '用户帮助' })).not.toBeInTheDocument();

    await user.click(triggerButton);

    expect(triggerButton).toHaveAttribute('aria-expanded', 'true');
    expect(await screen.findByRole('dialog', { name: '用户帮助' })).toBeInTheDocument();

    expect(screen.getByText('三场景操作指南（Web）')).toBeInTheDocument();
    expect(screen.getByText('点位仰视模式（Local mode）')).toBeInTheDocument();
    expect(screen.getByText('锁层模式（LayerGlobal mode）')).toBeInTheDocument();
    expect(screen.getByText('事件模式（Event mode）')).toBeInTheDocument();

    expect(screen.getByText('常见问题（FAQ）')).toBeInTheDocument();
    expect(screen.getByText('数据缺失处理')).toBeInTheDocument();
    expect(screen.getByText('性能模式切换')).toBeInTheDocument();
    expect(screen.getByText('数据归因说明')).toBeInTheDocument();

    const closeButton = await screen.findByRole('button', { name: '关闭弹窗' });
    await waitFor(() => expect(closeButton).toHaveFocus());

    await user.click(closeButton);
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: '用户帮助' })).not.toBeInTheDocument(),
    );

    expect(triggerButton).toHaveAttribute('aria-expanded', 'false');
    await waitFor(() => expect(triggerButton).toHaveFocus());
  });

  it('closes via Escape key', async () => {
    const user = userEvent.setup();
    render(<HelpLauncher />);

    const triggerButton = screen.getByRole('button', { name: '打开用户帮助' });
    await user.click(triggerButton);
    await screen.findByRole('dialog', { name: '用户帮助' });

    await user.keyboard('{Escape}');
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: '用户帮助' })).not.toBeInTheDocument(),
    );

    await waitFor(() => expect(triggerButton).toHaveFocus());
  });

  it('supports localized UI strings', async () => {
    const user = userEvent.setup();
    render(<HelpLauncher locale="en" />);

    const triggerButton = screen.getByRole('button', { name: 'Open help' });
    expect(triggerButton).toHaveAttribute('aria-haspopup', 'dialog');
    expect(triggerButton).toHaveAttribute('aria-expanded', 'false');

    await user.click(triggerButton);

    expect(await screen.findByRole('dialog', { name: 'Help' })).toBeInTheDocument();
    expect(screen.getByText('Core Workflows (Web)')).toBeInTheDocument();

    const closeButton = await screen.findByRole('button', { name: 'Close dialog' });
    expect(closeButton).toHaveTextContent('Close');
  });
});

