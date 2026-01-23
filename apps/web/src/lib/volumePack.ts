import { decompress } from 'fzstd';

export type VolumePackBBox = {
  west: number;
  south: number;
  east: number;
  north: number;
  bottom: number;
  top: number;
};

export type VolumePackHeader = {
  version?: number;
  bbox?: VolumePackBBox;
  shape: [number, number, number];
  dtype: 'uint8' | 'int16' | 'int32' | 'float32' | 'float64';
  scale?: number;
  offset?: number;
  compression?: 'zstd' | string;
  levels?: number[];
  variable?: string;
  valid_time?: string;
  [key: string]: unknown;
};

export type VolumePackDecoded<T extends ArrayBufferView = ArrayBufferView> = {
  header: VolumePackHeader;
  shape: [number, number, number];
  dtype: VolumePackHeader['dtype'];
  scale: number;
  offset: number;
  data: T;
};

const MAGIC = new Uint8Array([0x56, 0x4f, 0x4c, 0x50]); // "VOLP"
const MAX_HEADER_BYTES = 1024 * 1024;
const MAX_BODY_BYTES = 256 * 1024 * 1024;

const DTYPE_TABLE = {
  uint8: { bytesPerElement: 1, ctor: Uint8Array },
  int16: { bytesPerElement: 2, ctor: Int16Array },
  int32: { bytesPerElement: 4, ctor: Int32Array },
  float32: { bytesPerElement: 4, ctor: Float32Array },
  float64: { bytesPerElement: 8, ctor: Float64Array },
} as const;

function isLittleEndian(): boolean {
  const buffer = new ArrayBuffer(2);
  new DataView(buffer).setUint16(0, 0x00ff, true);
  return new Uint16Array(buffer)[0] === 0x00ff;
}

function byteswapInPlace(bytes: Uint8Array, elementSize: number): void {
  for (let i = 0; i + elementSize <= bytes.length; i += elementSize) {
    for (let a = 0, b = elementSize - 1; a < b; a += 1, b -= 1) {
      const tmp = bytes[i + a]!;
      bytes[i + a] = bytes[i + b]!;
      bytes[i + b] = tmp;
    }
  }
}

function asUint8Array(input: ArrayBuffer | Uint8Array): Uint8Array {
  return input instanceof Uint8Array ? input : new Uint8Array(input);
}

function parseShape(value: unknown): [number, number, number] {
  if (!Array.isArray(value) || value.length !== 3) {
    throw new Error('Volume Pack header.shape must be [levels, lat, lon]');
  }
  const shape = value.map((v) => Number(v)) as [number, number, number];
  if (!shape.every((n) => Number.isInteger(n) && n > 0)) {
    throw new Error('Volume Pack header.shape must contain positive integers');
  }
  return shape;
}

function parseDtype(value: unknown): VolumePackHeader['dtype'] {
  const dtype = String(value);
  if (!Object.hasOwn(DTYPE_TABLE, dtype)) {
    throw new Error(`Unsupported Volume Pack dtype: ${dtype}`);
  }
  return dtype as VolumePackHeader['dtype'];
}

export function decodeVolumePack(input: ArrayBuffer | Uint8Array): VolumePackDecoded {
  const bytes = asUint8Array(input);
  if (bytes.byteLength < 8) {
    throw new Error('Volume Pack payload is too small');
  }

  for (let i = 0; i < 4; i += 1) {
    if (bytes[i] !== MAGIC[i]) {
      throw new Error('Invalid Volume Pack magic');
    }
  }

  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const headerLen = view.getUint32(4, true);
  if (headerLen <= 0) {
    throw new Error('Invalid Volume Pack header length');
  }
  if (headerLen > MAX_HEADER_BYTES) {
    throw new Error('Volume Pack header is too large');
  }

  const headerStart = 8;
  const headerEnd = headerStart + headerLen;
  if (headerEnd > bytes.byteLength) {
    throw new Error('Volume Pack payload truncated while reading header');
  }

  const headerBytes = bytes.slice(headerStart, headerEnd);
  let headerUnknown: unknown;
  try {
    headerUnknown = JSON.parse(new TextDecoder().decode(headerBytes));
  } catch (error) {
    throw new Error('Invalid Volume Pack header JSON', { cause: error });
  }
  if (headerUnknown === null || typeof headerUnknown !== 'object' || Array.isArray(headerUnknown)) {
    throw new Error('Volume Pack header JSON must be an object');
  }
  const header = headerUnknown as VolumePackHeader;

  const version = Number(header.version ?? 1);
  if (!Number.isFinite(version) || version < 1) {
    header.version = 1;
  }

  const compression = String(header.compression ?? 'zstd').toLowerCase();
  if (compression !== 'zstd') {
    throw new Error(`Unsupported Volume Pack compression: ${compression}`);
  }

  const shape = parseShape(header.shape);
  const dtype = parseDtype(header.dtype);
  const { bytesPerElement, ctor } = DTYPE_TABLE[dtype];
  const scaleRaw = Number(header.scale ?? 1.0);
  const scale = Number.isFinite(scaleRaw) ? scaleRaw : 1.0;
  const offsetRaw = Number(header.offset ?? 0.0);
  const offset = Number.isFinite(offsetRaw) ? offsetRaw : 0.0;

  const elementsBig = BigInt(shape[0]) * BigInt(shape[1]) * BigInt(shape[2]);
  const expectedBytesBig = elementsBig * BigInt(bytesPerElement);
  if (expectedBytesBig > BigInt(MAX_BODY_BYTES)) {
    throw new Error('Volume Pack decoded body is too large');
  }
  const expectedBytes = Number(expectedBytesBig);

  const bodyCompressed = bytes.slice(headerEnd);
  const body = decompress(bodyCompressed);
  if (body.byteLength !== expectedBytes) {
    throw new Error(
      `Volume Pack decoded body size mismatch (expected=${expectedBytes}, got=${body.byteLength})`,
    );
  }

  // Copy to a fresh ArrayBuffer to avoid SharedArrayBuffer issues
  const bodyBuffer = new ArrayBuffer(body.byteLength);
  new Uint8Array(bodyBuffer).set(body);
  if (!isLittleEndian() && bytesPerElement > 1) {
    byteswapInPlace(new Uint8Array(bodyBuffer), bytesPerElement);
  }
  const data = new ctor(bodyBuffer);

  return {
    header,
    shape,
    dtype,
    scale,
    offset,
    data,
  };
}
