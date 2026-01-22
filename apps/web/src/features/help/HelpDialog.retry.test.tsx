import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

let accessCount = 0;

vi.mock('./helpContent', () => {
  accessCount = 0;
  return {
    get HELP_CONTENT() {
      accessCount += 1;
      if (accessCount === 1) throw new Error('boom');

      return {
        'zh-CN': {
          title: '用户帮助',
          subtitle: 'Mock subtitle zh',
          sections: [],
        },
        en: {
          title: 'Help',
          subtitle: 'Mock subtitle',
          sections: [
            {
              title: 'Mock section',
              items: [
                {
                  title: 'Mock item',
                  description: 'Mock description',
                  links: [{ label: 'Safe link', href: 'https://example.com' }],
                },
              ],
            },
          ],
        },
      };
    },
  };
});

import { HelpDialog } from './HelpDialog';

describe('HelpDialog (retry)', () => {
  it('retries loading content after a failure', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<HelpDialog open locale="en" onClose={() => {}} />);

    expect(
      await screen.findByText('Unable to load help content. Please try again.'),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(await screen.findByText('Mock subtitle')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'Mock section' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Safe link' })).toBeInTheDocument();
    expect(consoleSpy).toHaveBeenCalledTimes(1);
    consoleSpy.mockRestore();
  });
});

