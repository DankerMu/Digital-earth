import * as zstd from '@mongodb-js/zstd';
import { expect, test } from 'vitest';

import { decodeVolumePack } from './volumePack';

function encodeHeader(header: object): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(header));
}

async function buildPack(header: object, bodyRaw: Uint8Array): Promise<Uint8Array> {
  const headerBytes = encodeHeader(header);
  const headerLen = headerBytes.byteLength;

  const bodyCompressed = await zstd.compress(Buffer.from(bodyRaw));
  const out = new Uint8Array(8 + headerLen + bodyCompressed.byteLength);

  out.set([0x56, 0x4f, 0x4c, 0x50], 0); // "VOLP"
  new DataView(out.buffer).setUint32(4, headerLen, true);
  out.set(headerBytes, 8);
  out.set(bodyCompressed, 8 + headerLen);
  return out;
}

test('decodes float32 payload', async () => {
  const shape: [number, number, number] = [2, 2, 3];
  const values = Float32Array.from({ length: shape[0] * shape[1] * shape[2] }, (_, i) => i / 10);
  const bodyRaw = new Uint8Array(values.buffer);
  const header = {
    version: 1,
    shape,
    dtype: 'float32',
    scale: 1.0,
    offset: 0.0,
    compression: 'zstd',
    variable: 'cloud_density',
    valid_time: '2026-01-01T00:00:00Z',
  };

  const pack = await buildPack(header, bodyRaw);
  const decoded = decodeVolumePack(pack);

  expect(decoded.shape).toEqual(shape);
  expect(decoded.dtype).toBe('float32');
  expect(decoded.header.variable).toBe('cloud_density');
  expect(decoded.header.valid_time).toBe('2026-01-01T00:00:00Z');
  expect(decoded.data).toBeInstanceOf(Float32Array);

  const decodedValues = decoded.data as Float32Array;
  expect(Array.from(decodedValues)).toEqual(Array.from(values));
});

test('throws on invalid magic', () => {
  const bytes = new Uint8Array(8);
  bytes.set([0x4e, 0x4f, 0x50, 0x45], 0); // "NOPE"
  expect(() => decodeVolumePack(bytes)).toThrow(/magic/i);
});

test('throws on truncated header', () => {
  const out = new Uint8Array(12);
  out.set([0x56, 0x4f, 0x4c, 0x50], 0);
  new DataView(out.buffer).setUint32(4, 100, true);
  expect(() => decodeVolumePack(out)).toThrow(/truncated/i);
});

test('throws on header length zero', () => {
  const out = new Uint8Array(8);
  out.set([0x56, 0x4f, 0x4c, 0x50], 0);
  new DataView(out.buffer).setUint32(4, 0, true);
  expect(() => decodeVolumePack(out)).toThrow(/header length/i);
});

test('throws on header length exceeds maximum', () => {
  const out = new Uint8Array(8);
  out.set([0x56, 0x4f, 0x4c, 0x50], 0);
  new DataView(out.buffer).setUint32(4, 1024 * 1024 + 1, true);
  expect(() => decodeVolumePack(out)).toThrow(/header.*large/i);
});

test('throws on invalid header JSON', () => {
  const headerBytes = new Uint8Array([0x7b, 0x7d, 0x2c]); // "{},"
  const out = new Uint8Array(8 + headerBytes.byteLength);
  out.set([0x56, 0x4f, 0x4c, 0x50], 0);
  new DataView(out.buffer).setUint32(4, headerBytes.byteLength, true);
  out.set(headerBytes, 8);
  expect(() => decodeVolumePack(out)).toThrow(/header json/i);
});

test('throws on unsupported compression', async () => {
  const values = new Float32Array([1]);
  const pack = await buildPack(
    { shape: [1, 1, 1], dtype: 'float32', scale: 1, offset: 0, compression: 'lz4' },
    new Uint8Array(values.buffer),
  );
  expect(() => decodeVolumePack(pack)).toThrow(/compression/i);
});

test('throws on unsupported dtype', async () => {
  const body = new Uint8Array([0, 0, 0, 0]);
  const pack = await buildPack(
    { shape: [1, 1, 1], dtype: 'float16', scale: 1, offset: 0, compression: 'zstd' },
    body,
  );
  expect(() => decodeVolumePack(pack)).toThrow(/dtype/i);
});

test('throws on prototype-chain dtype', async () => {
  const values = new Float32Array([1]);
  const pack = await buildPack(
    { shape: [1, 1, 1], dtype: 'toString', scale: 1, offset: 0, compression: 'zstd' },
    new Uint8Array(values.buffer),
  );
  expect(() => decodeVolumePack(pack)).toThrow(/dtype/i);
});

test('throws on invalid shape', async () => {
  const body = new Uint8Array([0, 0, 0, 0]);
  const pack = await buildPack(
    { shape: [0, 1, 1], dtype: 'float32', scale: 1, offset: 0, compression: 'zstd' },
    body,
  );
  expect(() => decodeVolumePack(pack)).toThrow(/shape/i);
});

test('throws on decoded body size mismatch', async () => {
  const values = new Float32Array([1]);
  const pack = await buildPack(
    { shape: [1, 1, 2], dtype: 'float32', scale: 1, offset: 0, compression: 'zstd' },
    new Uint8Array(values.buffer),
  );
  expect(() => decodeVolumePack(pack)).toThrow(/size mismatch/i);
});
