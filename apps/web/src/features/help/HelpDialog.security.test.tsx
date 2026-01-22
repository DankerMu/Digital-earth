import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('./helpContent', () => {
  return {
    HELP_CONTENT: {
      'zh-CN': {
        title: '用户帮助',
        subtitle: '测试',
        sections: [],
      },
      en: {
        title: 'Help',
        subtitle: 'Security test',
        sections: [
          {
            title: 'Links',
            items: [
              {
                title: 'Item',
                description: 'Description',
                links: [
                  { label: 'Safe', href: 'https://example.com' },
                  { label: 'Evil', href: 'javascript:alert(1)' },
                ],
              },
            ],
          },
        ],
      },
    },
  };
});

import { HelpDialog } from './HelpDialog';

describe('HelpDialog (link safety)', () => {
  it('filters out non-http(s) href values', async () => {
    render(<HelpDialog open locale="en" onClose={() => {}} />);

    await screen.findByRole('dialog', { name: 'Help' });

    expect(screen.getByRole('link', { name: 'Safe' })).toHaveAttribute(
      'href',
      'https://example.com',
    );
    expect(screen.queryByRole('link', { name: 'Evil' })).not.toBeInTheDocument();
    expect(screen.queryByText('Evil')).not.toBeInTheDocument();
  });
});

