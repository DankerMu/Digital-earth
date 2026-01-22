import { useState } from 'react';

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { DisclaimerDialog } from './DisclaimerDialog';

describe('DisclaimerDialog', () => {
  it('returns null when closed', () => {
    render(<DisclaimerDialog open={false} onClose={() => {}} />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('renders locale content and only closes on overlay click', async () => {
    const onClose = vi.fn();
    render(<DisclaimerDialog open locale="en" onClose={onClose} />);

    const dialog = await screen.findByRole('dialog', { name: 'Data Sources & Disclaimer' });
    expect(dialog).toBeInTheDocument();

    fireEvent.mouseDown(dialog);
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.mouseDown(screen.getByTestId('disclaimer-overlay'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('uses noopener noreferrer for external links', async () => {
    render(<DisclaimerDialog open locale="en" onClose={() => {}} />);

    const link = await screen.findByRole('link', { name: 'CesiumJS' });
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('traps focus inside the dialog and hides background content', async () => {
    function Wrapper() {
      const [open, setOpen] = useState(false);

      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open
          </button>
          <button type="button">Background</button>

          <DisclaimerDialog open={open} locale="en" onClose={() => setOpen(false)} />
        </>
      );
    }

    const root = document.createElement('div');
    root.id = 'root';
    document.body.appendChild(root);

    const user = userEvent.setup();
    render(<Wrapper />, { container: root });

    const openButton = screen.getByRole('button', { name: 'Open' });
    const backgroundButton = screen.getByRole('button', { name: 'Background' });

    openButton.focus();
    expect(openButton).toHaveFocus();

    await user.click(openButton);

    const dialog = await screen.findByRole('dialog', { name: 'Data Sources & Disclaimer' });
    const closeButton = screen.getByRole('button', { name: 'Close dialog' });
    await waitFor(() => expect(closeButton).toHaveFocus());

    expect(root).toHaveAttribute('aria-hidden', 'true');
    expect(root).toHaveAttribute('inert');

    await user.tab({ shift: true });
    expect(screen.getByRole('link', { name: 'GitHub Repo' })).toHaveFocus();

    await user.tab();
    expect(closeButton).toHaveFocus();

    for (let index = 0; index < 8; index += 1) {
      await user.tab();
      expect(backgroundButton).not.toHaveFocus();
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }

    await user.click(closeButton);

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(root).not.toHaveAttribute('aria-hidden');
    expect(root).not.toHaveAttribute('inert');
    await waitFor(() => expect(openButton).toHaveFocus());

    root.remove();
  });

  it('restores focus to the trigger element on close', async () => {
    function Wrapper() {
      const [open, setOpen] = useState(false);

      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open
          </button>

          {open ? (
            <DisclaimerDialog open locale="en" onClose={() => setOpen(false)} />
          ) : null}
        </>
      );
    }

    const user = userEvent.setup();
    render(<Wrapper />);

    const trigger = screen.getByRole('button', { name: 'Open' });
    trigger.focus();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    await screen.findByRole('dialog', { name: 'Data Sources & Disclaimer' });

    const closeButton = screen.getByRole('button', { name: 'Close dialog' });
    await waitFor(() => expect(closeButton).toHaveFocus());

    await user.click(closeButton);

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
