import { describe, expect, it } from 'vitest';

import { VolumeCache } from './volumeCache';

describe('VolumeCache', () => {
  it('evicts the least-recently-used entry', () => {
    const cache = new VolumeCache(2);
    const a = new ArrayBuffer(1);
    const b = new ArrayBuffer(1);
    const c = new ArrayBuffer(1);

    cache.set('a', a);
    cache.set('b', b);

    expect(cache.get('a')).toBe(a);

    cache.set('c', c);

    expect(cache.get('b')).toBeNull();
    expect(cache.get('a')).toBe(a);
    expect(cache.get('c')).toBe(c);
  });
});
