import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { LocalInfoPanel } from './LocalInfoPanel';

describe('LocalInfoPanel', () => {
  it('renders location, height, time key, and active layer', () => {
    render(
      <LocalInfoPanel
        lat={30.123456}
        lon={120.987654}
        heightMeters={1234.56}
        timeKey="2024-01-15T00:00:00Z"
        activeLayer={{
          id: 'cloud',
          type: 'cloud',
          variable: 'tcc',
          opacity: 1,
          visible: true,
          zIndex: 10,
        }}
        canGoBack={true}
        onBack={() => {}}
      />,
    );

    expect(screen.getByLabelText('Local info')).toHaveTextContent('30.1235, 120.9877');
    expect(screen.getByText('1235')).toBeInTheDocument();
    expect(screen.getByText('2024-01-15T00:00:00Z')).toBeInTheDocument();
    expect(screen.getByText('cloud:tcc')).toBeInTheDocument();
  });

  it('calls onBack when back button is clicked', async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();

    render(
      <LocalInfoPanel
        lat={30}
        lon={120}
        heightMeters={0}
        timeKey={null}
        activeLayer={null}
        canGoBack={true}
        onBack={onBack}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Back to previous view' }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('disables back button when canGoBack is false', () => {
    render(
      <LocalInfoPanel
        lat={30}
        lon={120}
        timeKey={null}
        activeLayer={null}
        canGoBack={false}
        onBack={() => {}}
      />,
    );

    expect(screen.getByRole('button', { name: 'Back to previous view' })).toBeDisabled();
  });
});

