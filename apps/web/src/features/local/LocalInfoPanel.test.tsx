import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { useAircraftDemoStore } from '../../state/aircraftDemo';
import { DEFAULT_CAMERA_PERSPECTIVE_ID, useCameraPerspectiveStore } from '../../state/cameraPerspective';
import { DEFAULT_TIME_KEY } from '../../state/time';
import { LocalInfoPanel } from './LocalInfoPanel';

describe('LocalInfoPanel', () => {
  it('renders location, height, time key, and active layer', () => {
    localStorage.removeItem('digital-earth.cameraPerspective');
    useCameraPerspectiveStore.setState({ cameraPerspectiveId: DEFAULT_CAMERA_PERSPECTIVE_ID });
    localStorage.removeItem('digital-earth.aircraftDemo');
    useAircraftDemoStore.setState({ enabled: false });

    render(
      <LocalInfoPanel
        lat={30.123456}
        lon={120.987654}
        heightMeters={1234.56}
        timeKey={DEFAULT_TIME_KEY}
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
        onLockLayer={() => {}}
      />,
    );

    expect(screen.getByLabelText('Local info')).toHaveTextContent('30.1235, 120.9877');
    expect(screen.getByText('1235')).toBeInTheDocument();
    expect(screen.getByText(DEFAULT_TIME_KEY)).toBeInTheDocument();
    expect(screen.getByText('cloud:tcc')).toBeInTheDocument();
  });

  it('calls onBack when back button is clicked', async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();

    localStorage.removeItem('digital-earth.cameraPerspective');
    useCameraPerspectiveStore.setState({ cameraPerspectiveId: DEFAULT_CAMERA_PERSPECTIVE_ID });
    localStorage.removeItem('digital-earth.aircraftDemo');
    useAircraftDemoStore.setState({ enabled: false });

    render(
      <LocalInfoPanel
        lat={30}
        lon={120}
        heightMeters={0}
        timeKey={null}
        activeLayer={null}
        canGoBack={true}
        onBack={onBack}
        onLockLayer={() => {}}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Back to previous view' }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('disables back button when canGoBack is false', () => {
    localStorage.removeItem('digital-earth.cameraPerspective');
    useCameraPerspectiveStore.setState({ cameraPerspectiveId: DEFAULT_CAMERA_PERSPECTIVE_ID });
    localStorage.removeItem('digital-earth.aircraftDemo');
    useAircraftDemoStore.setState({ enabled: false });

    render(
      <LocalInfoPanel
        lat={30}
        lon={120}
        timeKey={null}
        activeLayer={null}
        canGoBack={false}
        onBack={() => {}}
        onLockLayer={() => {}}
      />,
    );

    expect(screen.getByRole('button', { name: 'Back to previous view' })).toBeDisabled();
  });

  it('updates cameraPerspectiveId when selecting a new perspective', async () => {
    const user = userEvent.setup();

    localStorage.removeItem('digital-earth.cameraPerspective');
    useCameraPerspectiveStore.setState({ cameraPerspectiveId: DEFAULT_CAMERA_PERSPECTIVE_ID });
    localStorage.removeItem('digital-earth.aircraftDemo');
    useAircraftDemoStore.setState({ enabled: false });

    render(
      <LocalInfoPanel
        lat={30}
        lon={120}
        timeKey={null}
        activeLayer={null}
        canGoBack={false}
        onBack={() => {}}
        onLockLayer={() => {}}
      />,
    );

    const group = screen.getByRole('group', { name: 'Camera perspective' });
    expect(group).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '仰视' }));
    expect(useCameraPerspectiveStore.getState().cameraPerspectiveId).toBe('upward');
    expect(screen.getByRole('button', { name: '仰视' })).toHaveAttribute('aria-pressed', 'true');

    await user.click(screen.getByRole('button', { name: '平视' }));
    expect(useCameraPerspectiveStore.getState().cameraPerspectiveId).toBe('forward');
  });

  it('hides lock button when there is no active layer', () => {
    localStorage.removeItem('digital-earth.cameraPerspective');
    useCameraPerspectiveStore.setState({ cameraPerspectiveId: DEFAULT_CAMERA_PERSPECTIVE_ID });
    localStorage.removeItem('digital-earth.aircraftDemo');
    useAircraftDemoStore.setState({ enabled: false });

    render(
      <LocalInfoPanel
        lat={30}
        lon={120}
        timeKey={null}
        activeLayer={null}
        canGoBack={false}
        onBack={() => {}}
        onLockLayer={() => {}}
      />,
    );

    expect(screen.queryByRole('button', { name: '锁定当前层' })).toBeNull();
  });

  it('calls onLockLayer when lock button is clicked', async () => {
    const user = userEvent.setup();
    const onLockLayer = vi.fn();

    localStorage.removeItem('digital-earth.cameraPerspective');
    useCameraPerspectiveStore.setState({ cameraPerspectiveId: DEFAULT_CAMERA_PERSPECTIVE_ID });
    localStorage.removeItem('digital-earth.aircraftDemo');
    useAircraftDemoStore.setState({ enabled: false });

    render(
      <LocalInfoPanel
        lat={30}
        lon={120}
        timeKey={null}
        activeLayer={{
          id: 'cloud',
          type: 'cloud',
          variable: 'tcc',
          opacity: 1,
          visible: true,
          zIndex: 10,
        }}
        canGoBack={false}
        onBack={() => {}}
        onLockLayer={onLockLayer}
      />,
    );

    await user.click(screen.getByRole('button', { name: '锁定当前层' }));
    expect(onLockLayer).toHaveBeenCalledTimes(1);
  });

  it('toggles aircraft demo checkbox', async () => {
    const user = userEvent.setup();

    localStorage.removeItem('digital-earth.cameraPerspective');
    useCameraPerspectiveStore.setState({ cameraPerspectiveId: DEFAULT_CAMERA_PERSPECTIVE_ID });
    localStorage.removeItem('digital-earth.aircraftDemo');
    useAircraftDemoStore.setState({ enabled: false });

    render(
      <LocalInfoPanel
        lat={30}
        lon={120}
        timeKey={null}
        activeLayer={null}
        canGoBack={false}
        onBack={() => {}}
        onLockLayer={() => {}}
      />,
    );

    const checkbox = screen.getByRole('checkbox', { name: '显示飞行器' });
    expect(checkbox).not.toBeChecked();

    await user.click(checkbox);
    expect(useAircraftDemoStore.getState().enabled).toBe(true);
  });
});
