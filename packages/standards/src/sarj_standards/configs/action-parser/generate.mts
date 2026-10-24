import { buildSync } from 'esbuild';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const directory = fileURLToPath(new URL('.', import.meta.url));
const output = new URL('../action-parser.cjs', import.meta.url);
const result = buildSync({
  absWorkingDir: directory,
  entryPoints: ['index.mts'],
  bundle: true,
  platform: 'node',
  target: 'node20',
  format: 'cjs',
  minify: true,
  legalComments: 'inline',
  write: false,
});
const bytes = result.outputFiles[0]!.contents;
if (process.argv.includes('--check')) {
  if (!readFileSync(output).equals(bytes)) throw new Error('Run npm run build to refresh the pinned action parser bundle');
} else {
  writeFileSync(output, bytes);
}
