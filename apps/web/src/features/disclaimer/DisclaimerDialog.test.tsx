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

  it('renders locale content and only closes on overlay click', () => {
    const onClose = vi.fn();
    render(<DisclaimerDialog open locale="en" onClose={onClose} />);

    const dialog = screen.getByRole('dialog', { name: 'Data Sources & Disclaimer' });
    expect(dialog).toBeInTheDocument();

    fireEvent.mouseDown(dialog);
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.mouseDown(screen.getByTestId('disclaimer-overlay'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('uses noopener noreferrer for external links', () => {
    render(<DisclaimerDialog open locale="en" onClose={() => {}} />);

    const link = screen.getByRole('link', { name: 'CesiumJS' });
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
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
