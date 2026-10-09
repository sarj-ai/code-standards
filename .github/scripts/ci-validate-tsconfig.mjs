import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const directory = process.argv[2] ?? '.';
for (const file of ['base.json', 'strict.json']) {
  JSON.parse(readFileSync(join(directory, file), 'utf8'));
}
