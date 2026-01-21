import { describe, expect, it, vi } from 'vitest';

const STORAGE_KEY = 'digital-earth.eventAutoLayers';

async function importFresh() {
  vi.resetModules();
  return await import('./eventAutoLayers');
}

function writeStorage(value: unknown) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
}

describe('eventAutoLayers store', () => {
  it('defaults to restoreOnExit=true with empty overrides', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useEventAutoLayersStore } = await importFresh();

    expect(useEventAutoLayersStore.getState().restoreOnExit).toBe(true);
    expect(useEventAutoLayersStore.getState().overrides).toEqual({});
  });

  it('provides the snow template and canonicalizes chinese titles', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useEventAutoLayersStore } = await importFresh();

    const available = ['wind', 'temperature', 'cloud', 'precipitation'];

    expect(useEventAutoLayersStore.getState().getTemplateForEvent('snow', available)).toEqual([
      'precipitation',
      'temperature',
      'cloud',
    ]);

    expect(useEventAutoLayersStore.getState().getTemplateForEvent('降雪', available)).toEqual([
      'precipitation',
      'temperature',
      'cloud',
    ]);

    expect(useEventAutoLayersStore.getState().getTemplateForEvent('Snowfall Warning', available)).toEqual([
      'precipitation',
      'temperature',
      'cloud',
    ]);
  });

  it('includes snow depth when an optional snow depth layer exists', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useEventAutoLayersStore } = await importFresh();

    expect(
      useEventAutoLayersStore.getState().getTemplateForEvent('snow', [
        'temperature',
        'cloud',
        'precipitation',
        'snowDepth',
      ]),
    ).toEqual(['precipitation', 'temperature', 'cloud', 'snowDepth']);
  });

  it('supports user overrides and persists them', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useEventAutoLayersStore } = await importFresh();

    useEventAutoLayersStore.getState().setOverride('snow', [' wind ', 'cloud', '', 'cloud']);

    expect(useEventAutoLayersStore.getState().overrides).toEqual({
      snow: ['wind', 'cloud'],
    });

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as unknown;
    expect(persisted).toMatchObject({
      restoreOnExit: true,
      overrides: { snow: ['wind', 'cloud'] },
    });

    expect(
      useEventAutoLayersStore.getState().getTemplateForEvent('snow', ['cloud', 'wind']),
    ).toEqual(['wind', 'cloud']);
  });

  it('clears overrides when setting an empty template', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useEventAutoLayersStore } = await importFresh();

    useEventAutoLayersStore.getState().setOverride('snow', ['wind']);
    useEventAutoLayersStore.getState().setOverride('snow', []);

    expect(useEventAutoLayersStore.getState().overrides).toEqual({});
  });

  it('restores persisted settings and ignores invalid entries', async () => {
    writeStorage({
      restoreOnExit: false,
      overrides: {
        snow: ['temperature', null, 'temperature', 'wind'],
        ' ': ['cloud'],
        nope: 'not-an-array',
      },
    });

    const { useEventAutoLayersStore } = await importFresh();
    const state = useEventAutoLayersStore.getState();

    expect(state.restoreOnExit).toBe(false);
    expect(state.overrides).toEqual({
      snow: ['temperature', 'wind'],
    });

    expect(state.getTemplateForEvent('snow', ['temperature'])).toEqual(['temperature']);
  });

  it('setState supports resetting restoreOnExit and overrides', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { useEventAutoLayersStore } = await importFresh();

    useEventAutoLayersStore.setState({
      restoreOnExit: false,
      overrides: { snow: ['wind'] },
    });

    expect(useEventAutoLayersStore.getState().restoreOnExit).toBe(false);
    expect(useEventAutoLayersStore.getState().overrides).toEqual({ snow: ['wind'] });
  });
});

