import { describe, expect, it, vi } from 'vitest';

import { isCesiumDestroyed, requestViewerRender } from './cesiumSafe';

describe('requestViewerRender', () => {
  it('calls scene.requestRender when available', () => {
    const requestRender = vi.fn();
    const viewer = { scene: { requestRender } };

    requestViewerRender(viewer);

    expect(requestRender).toHaveBeenCalledTimes(1);
  });

  it('ignores errors when accessing scene', () => {
    const viewer: Record<string, unknown> = {};
    Object.defineProperty(viewer, 'scene', {
      get() {
        throw new Error('boom');
      },
    });

    expect(() => requestViewerRender(viewer)).not.toThrow();
  });
});

describe('isCesiumDestroyed', () => {
  it('returns false when no isDestroyed exists', () => {
    expect(isCesiumDestroyed({})).toBe(false);
  });

  it('returns the value of isDestroyed when present', () => {
    expect(isCesiumDestroyed({ isDestroyed: () => false })).toBe(false);
    expect(isCesiumDestroyed({ isDestroyed: () => true })).toBe(true);
  });

  it('returns true when isDestroyed throws', () => {
    expect(
      isCesiumDestroyed({
        isDestroyed: () => {
          throw new Error('teardown');
        },
      }),
    ).toBe(true);
  });
});

