import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { mkdtemp, mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const packageRoot = fileURLToPath(new URL('..', import.meta.url));
const manifest = JSON.parse(readFileSync(join(packageRoot, 'package.json'), 'utf8'));
const expectedExports = {
  './styles.css': './src/styles/theme.css',
  './PageAnchor.astro': './src/components/PageAnchor.astro',
  './ReferencePage.astro': './src/components/ReferencePage.astro',
  './Breadcrumbs.astro': './src/components/Breadcrumbs.astro',
};

assert.deepEqual(manifest.exports, expectedExports);
assert.deepEqual(manifest.files, ['src', 'README.md', 'LICENSE']);
assert.deepEqual(manifest.sideEffects, ['./src/styles/theme.css']);
assert.equal(manifest.publishConfig?.access, 'public');

const workingDirectory = await mkdtemp(join(tmpdir(), 'sarj-docs-ui-contract-'));

try {
  const packOutput = execFileSync(
    'npm',
    ['pack', '--json', '--ignore-scripts', '--pack-destination', workingDirectory],
    { cwd: packageRoot, encoding: 'utf8' },
  );
  const packDescription = JSON.parse(packOutput);
  const packed = Array.isArray(packDescription) ? packDescription[0] : packDescription;
  assert.ok(packed, 'npm pack returned no package description');

  const expectedFiles = new Set([
    'LICENSE',
    'README.md',
    'package.json',
    'src/components/Breadcrumbs.astro',
    'src/components/PageAnchor.astro',
    'src/components/ReferencePage.astro',
    'src/styles/theme.css',
  ]);
  assert.deepEqual(new Set(packed.files.map(({ path }) => path)), expectedFiles);

  const consumerRoot = join(workingDirectory, 'consumer');
  await mkdir(join(consumerRoot, 'src', 'pages'), { recursive: true });
  const tarballPath = join(workingDirectory, packed.filename);
  writeFileSync(
    join(consumerRoot, 'package.json'),
    `${JSON.stringify(
      {
        name: 'docs-ui-consumer-smoke',
        private: true,
        type: 'module',
        dependencies: {
          '@astrojs/check': '0.9.10',
          '@astrojs/starlight': '0.41.7',
          '@sarj/docs-ui': `file:${tarballPath}`,
          astro: '7.2.3',
          typescript: '6.0.3',
        },
      },
      null,
      2,
    )}\n`,
  );
  writeFileSync(
    join(consumerRoot, 'astro.config.mjs'),
    `import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';

export default defineConfig({
  output: 'static',
  integrations: [
    starlight({
      title: 'Consumer',
      customCss: ['@sarj/docs-ui/styles.css'],
      components: { PageTitle: '@sarj/docs-ui/PageAnchor.astro' },
      sidebar: [{ label: 'Home', link: '/' }],
    }),
  ],
});
`,
  );
  writeFileSync(
    join(consumerRoot, 'tsconfig.json'),
    `${JSON.stringify({ extends: 'astro/tsconfigs/strict' }, null, 2)}\n`,
  );
  writeFileSync(
    join(consumerRoot, 'src', 'pages', 'index.astro'),
    `---
import Breadcrumbs from '@sarj/docs-ui/Breadcrumbs.astro';
import ReferencePage from '@sarj/docs-ui/ReferencePage.astro';

const sidebar = [{ label: 'Home', link: '/' }];
---

<ReferencePage title="Consumer" description="Package consumer smoke test" {sidebar}>
  <Breadcrumbs ancestors={[]} current="Consumer" />
  <h1>Consumer</h1>
</ReferencePage>
`,
  );

  execFileSync('npm', ['install', '--ignore-scripts', '--no-audit', '--no-fund'], {
    cwd: consumerRoot,
    stdio: 'inherit',
  });
  execFileSync(join(consumerRoot, 'node_modules', '.bin', 'astro'), ['check'], {
    cwd: consumerRoot,
    stdio: 'inherit',
  });
  execFileSync(join(consumerRoot, 'node_modules', '.bin', 'astro'), ['build'], {
    cwd: consumerRoot,
    stdio: 'inherit',
  });
} finally {
  await rm(workingDirectory, { recursive: true, force: true });
}
