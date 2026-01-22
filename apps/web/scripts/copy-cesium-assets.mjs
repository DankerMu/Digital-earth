import fs from 'node:fs/promises';
import path from 'node:path';

const CESIUM_SUBDIRS = ['Assets', 'ThirdParty', 'Widgets', 'Workers'];

async function exists(p) {
  try {
    await fs.access(p);
    return true;
  } catch {
    return false;
  }
}

async function copyDirectory(srcDir, destDir) {
  await fs.mkdir(destDir, { recursive: true });
  await fs.cp(srcDir, destDir, { recursive: true, force: true });
}

async function main() {
  const root = process.cwd();
  const cesiumRoot = path.join(root, 'node_modules', 'cesium', 'Build', 'Cesium');
  const outDir = path.join(root, 'dist', 'assets');

  if (!(await exists(path.join(root, 'dist')))) {
    throw new Error('Missing dist output. Run `pnpm run build` first.');
  }

  for (const dir of CESIUM_SUBDIRS) {
    const srcDir = path.join(cesiumRoot, dir);
    const destDir = path.join(outDir, dir);
    if (!(await exists(srcDir))) {
      throw new Error(`Cesium build dir missing: ${srcDir}`);
    }
    await copyDirectory(srcDir, destDir);
  }
}

await main();

