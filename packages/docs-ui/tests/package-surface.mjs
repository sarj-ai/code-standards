import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const packageRoot = fileURLToPath(new URL('..', import.meta.url));

function exportedFiles(exportsValue) {
  if (typeof exportsValue === 'string') return [exportsValue.replace(/^\.\//, '')];
  if (Array.isArray(exportsValue)) return exportsValue.flatMap(exportedFiles);
  if (exportsValue && typeof exportsValue === 'object') return Object.values(exportsValue).flatMap(exportedFiles);
  return [];
}

export function expectedPackageFiles(manifest) {
  return new Set(['LICENSE', 'README.md', 'package.json', ...exportedFiles(manifest.exports)]);
}

export function verifyPackageSurface(tarballPath) {
  const manifest = JSON.parse(readFileSync(join(packageRoot, 'package.json'), 'utf8'));
  const archiveMembers = execFileSync('tar', ['-tzf', tarballPath], { encoding: 'utf8' })
    .trim()
    .split('\n')
    .map((path) => path.replace(/^package\//, ''));
  assert.deepEqual(new Set(archiveMembers), expectedPackageFiles(manifest));

  const packedManifest = JSON.parse(execFileSync('tar', ['-xOf', tarballPath, 'package/package.json'], {
    encoding: 'utf8',
  }));
  assert.equal(packedManifest.name, manifest.name);
  assert.equal(packedManifest.version, manifest.version);
}

const invokedPath = process.argv[1];
if (invokedPath && fileURLToPath(import.meta.url) === invokedPath) {
  const tarballPath = process.argv[2];
  assert.ok(tarballPath, 'usage: node tests/package-surface.mjs PATH_TO_TARBALL');
  verifyPackageSurface(tarballPath);
}
