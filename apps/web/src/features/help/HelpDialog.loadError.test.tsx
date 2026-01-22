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
    render(<HelpDialog open locale="en" onClose={() => {}} />);

    expect(await screen.findByText('Failed to load: boom')).toBeInTheDocument();
  });
});
