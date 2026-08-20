import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { mkdtemp, mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { componentCatalog, themeTokenCatalog } from '../src/catalog.ts';
import { verifyPackageSurface } from './package-surface.mjs';

const packageRoot = fileURLToPath(new URL('..', import.meta.url));
const manifest = JSON.parse(readFileSync(join(packageRoot, 'package.json'), 'utf8'));
const componentExportNames = Object.values(componentCatalog)
  .map(({ exportPath }) => `.${exportPath.replace('@sarj/docs-ui', '')}`)
  .sort();
assert.deepEqual(
  Object.keys(manifest.exports).filter((name) => name.endsWith('.astro')).sort(),
  componentExportNames,
);
assert.deepEqual(manifest.files, ['src', 'README.md', 'LICENSE']);
assert.deepEqual(manifest.sideEffects, ['./src/styles/theme.css']);
assert.equal(manifest.publishConfig?.access, 'public');

const themeSource = readFileSync(join(packageRoot, 'src', 'styles', 'theme.css'), 'utf8');
const declaredTokens = [...themeSource.matchAll(/^\s*(--sarj-[a-z-]+):/gmu)].map((match) => match[1]);
assert.deepEqual(new Set(declaredTokens), new Set(themeTokenCatalog.map(({ cssName }) => cssName)));

const workingDirectory = await mkdtemp(join(tmpdir(), 'sarj-docs-ui-contract-'));

try {
  execFileSync('npm', ['pack', '--ignore-scripts', '--pack-destination', workingDirectory], {
    cwd: packageRoot,
    encoding: 'utf8',
  });
  const archiveName = `sarj-docs-ui-${manifest.version}.tgz`;
  const tarballPath = join(workingDirectory, archiveName);

  verifyPackageSurface(tarballPath);

  const consumerRoot = join(workingDirectory, 'consumer');
  await mkdir(join(consumerRoot, 'src', 'pages'), { recursive: true });
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
          astro: '7.2.4',
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
  site: 'https://example.invalid',
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
import { componentCatalog } from '@sarj/docs-ui/catalog';
import type { BreadcrumbsProps } from '@sarj/docs-ui/contracts';

const sidebar = [{ label: 'Home', link: '/' }];
const breadcrumbs = {
  ancestors: [],
  current: componentCatalog.Breadcrumbs.purpose,
} satisfies BreadcrumbsProps;
---

<ReferencePage title="Consumer" description="Package consumer smoke test" {sidebar}>
  <Breadcrumbs {...breadcrumbs} />
  <h1>Consumer</h1>
</ReferencePage>
`,
  );
  const behaviorPage = (properties) => `---
import ReferencePage from '@sarj/docs-ui/ReferencePage.astro';
const sidebar = [{ label: 'Home', link: '/' }];
---
<ReferencePage title="Behavior" description="ReferencePage behavior" {sidebar} ${properties}>
  <h1>Behavior</h1>
</ReferencePage>
`;
  writeFileSync(
    join(consumerRoot, 'src', 'pages', 'explicit.astro'),
    behaviorPage('searchable={false} indexable={false}'),
  );
  writeFileSync(
    join(consumerRoot, 'src', 'pages', 'legacy.astro'),
    behaviorPage('discovery="unlisted"'),
  );
  writeFileSync(
    join(consumerRoot, 'src', 'pages', 'precedence.astro'),
    behaviorPage('discovery="unlisted" searchable={true} indexable={true}'),
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
  const explicit = readFileSync(join(consumerRoot, 'dist', 'explicit', 'index.html'), 'utf8');
  assert.match(explicit, /name="robots" content="noindex, nofollow"/u);
  assert.match(explicit, /data-pagefind-ignore="true"/u);
  const legacy = readFileSync(join(consumerRoot, 'dist', 'legacy', 'index.html'), 'utf8');
  assert.match(legacy, /name="robots" content="noindex, nofollow"/u);
  assert.match(legacy, /data-pagefind-ignore="true"/u);
  const precedence = readFileSync(join(consumerRoot, 'dist', 'precedence', 'index.html'), 'utf8');
  assert.doesNotMatch(precedence, /name="robots" content="noindex, nofollow"/u);
  assert.match(precedence, /data-pagefind-body="true"/u);
} finally {
  await rm(workingDirectory, { recursive: true, force: true });
}
