import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('./helpContent', () => {
  return {
    get HELP_CONTENT() {
      throw new Error('boom');
    },
  };
});

import { HelpDialog } from './HelpDialog';

describe('HelpDialog (load error)', () => {
  it('renders a localized load error message', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<HelpDialog open locale="en" onClose={() => {}} />);

    expect(
      await screen.findByText('Unable to load help content. Please try again.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('boom')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(consoleSpy).toHaveBeenCalledWith(
      '[HelpDialog] Failed to load help content',
      expect.any(Error),
    );
    consoleSpy.mockRestore();
  });
});
