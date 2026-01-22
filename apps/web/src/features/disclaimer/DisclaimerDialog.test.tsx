import { fireEvent, render, screen } from '@testing-library/react';
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
});

