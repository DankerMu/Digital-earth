import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

import * as zstd from '@mongodb-js/zstd';

function clamp01(value) {
  if (value <= 0) return 0;
  if (value >= 1) return 1;
  return value;
}

function smoothstep(edge0, edge1, x) {
  const t = clamp01((x - edge0) / (edge1 - edge0));
  return t * t * (3 - 2 * t);
}

function hash3(x, y, z) {
  // Deterministic 32-bit integer hash (cheap noise source).
  let h = x * 374761393 + y * 668265263 + z * 2147483647;
  h = (h ^ (h >>> 13)) >>> 0;
  h = (h * 1274126177) >>> 0;
  return h / 0xffffffff;
}

function buildDensityField({ depth, height, width }) {
  const out = new Uint8Array(depth * height * width);
  const cx = (width - 1) / 2;
  const cy = (height - 1) / 2;
  const cz = (depth - 1) / 2;
  const scale = 2 / Math.max(width - 1, height - 1, depth - 1);

  for (let z = 0; z < depth; z += 1) {
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const nx = (x - cx) * scale;
        const ny = (y - cy) * scale;
        const nz = (z - cz) * scale;

        const r = Math.sqrt(nx * nx + ny * ny + nz * nz);
        const base = 1 - smoothstep(0.35, 1.0, r);

        const n = hash3(x, y, z);
        const detail = 0.75 + 0.25 * n;

        const density = clamp01(base * detail);
        const idx = (z * height + y) * width + x;
        out[idx] = Math.round(density * 255);
      }
    }
  }

  return out;
}

function encodeHeader(header) {
  return new TextEncoder().encode(JSON.stringify(header));
}

async function writeVolumePack({ outFile, header, bodyRaw }) {
  const headerBytes = encodeHeader(header);
  const headerLen = headerBytes.byteLength;
  const bodyCompressed = await zstd.compress(Buffer.from(bodyRaw));
  const out = new Uint8Array(8 + headerLen + bodyCompressed.byteLength);

  out.set([0x56, 0x4f, 0x4c, 0x50], 0); // "VOLP"
  new DataView(out.buffer).setUint32(4, headerLen, true);
  out.set(headerBytes, 8);
  out.set(bodyCompressed, 8 + headerLen);

  await mkdir(path.dirname(outFile), { recursive: true });
  await writeFile(outFile, out);
  return { bytes: out.byteLength, headerBytes: headerLen, bodyBytes: bodyCompressed.byteLength };
}

async function main() {
  const shape = [64, 64, 64]; // [levels, lat, lon]
  const [depth, height, width] = shape;

  const data = buildDensityField({ depth, height, width });

  const header = {
    version: 1,
    bbox: {
      west: 116.1,
      south: 39.7,
      east: 116.6,
      north: 40.1,
      bottom: 0,
      top: 12_000,
    },
    shape,
    dtype: 'uint8',
    scale: 1 / 255,
    offset: 0,
    compression: 'zstd',
    variable: 'cloud_density',
    valid_time: new Date().toISOString(),
  };

  const outFile = path.resolve('apps/web/public/volumes/demo-voxel-cloud.volp');
  const stats = await writeVolumePack({ outFile, header, bodyRaw: data });

  console.log(
    `[voxel-cloud] wrote ${outFile} (${stats.bytes} bytes; header=${stats.headerBytes}; body.zstd=${stats.bodyBytes})`,
  );
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
