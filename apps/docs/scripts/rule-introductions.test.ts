import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test, { type TestContext } from 'node:test';
import { pathToFileURL } from 'node:url';

import { ruleIntroductions } from '../src/lib/rule-introductions.ts';

async function history(t: TestContext) {
  const root = await mkdtemp(join(tmpdir(), 'rule-introduction-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const git = (...args: string[]) => execFileSync('git', args, {
    cwd: root,
    encoding: 'utf8',
    env: { ...process.env, GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_SYSTEM: '/dev/null' },
  }).trim();
  git('init', '--initial-branch=main');
  const commit = (date: string) => {
    git('add', '.');
    return execFileSync('git', ['-c', 'user.name=History fixture', '-c', 'user.email=history@example.invalid', 'commit', '-m', 'Add rule'], {
      cwd: root,
      encoding: 'utf8',
      env: { ...process.env, GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_SYSTEM: '/dev/null', GIT_AUTHOR_DATE: date, GIT_COMMITTER_DATE: date },
    });
  };
  return { root, git, commit };
}

void test('introduction dates survive renames and distinguish rules sharing a source file', async (t) => {
  const { root, git, commit } = await history(t);
  await mkdir(join(root, 'rules'));
  await writeFile(join(root, 'rules/old.ts'), "export const first = 'first-rule';\n");
  commit('2025-01-02T12:00:00Z');
  const first = git('rev-parse', 'HEAD');
  git('mv', 'rules/old.ts', 'rules/current.ts');
  commit('2025-02-03T12:00:00Z');
  await writeFile(join(root, 'rules/current.ts'), "export const first = 'first-rule';\nexport const second = 'second-rule';\n");
  commit('2025-03-04T12:00:00Z');
  const dates = await ruleIntroductions(root, [
    { id: 'standalone', path: 'rules/current.ts' },
    { id: 'first', path: 'rules/current.ts', marker: 'first-rule' },
    { id: 'second', path: 'rules/current.ts', marker: 'second-rule' },
    { id: 'uncommitted', path: 'rules/current.ts', marker: 'uncommitted-rule' },
  ]);
  assert.deepEqual(dates.get('standalone'), { commit: first, introducedAt: '2025-01-02T12:00:00.000Z' });
  assert.deepEqual(dates.get('first'), dates.get('standalone'));
  assert.equal(dates.get('second')?.introducedAt, '2025-03-04T12:00:00.000Z');
  assert.equal(dates.get('uncommitted'), null);
});

void test('rules registered through imports retain the original definition date', async (t) => {
  const { root, commit } = await history(t);
  await mkdir(join(root, 'rules'));
  await writeFile(join(root, 'rules/definition.ts'), "export const ID = 'imported-rule';\n");
  commit('2025-01-02T12:00:00Z');
  await writeFile(join(root, 'rules/registry.ts'), "import { ID } from './definition';\nexport const rules = [ID];\n");
  commit('2025-03-04T12:00:00Z');
  const sources = [
    { id: 'imported', path: 'rules/registry.ts', marker: 'imported-rule' },
    { id: 'imported', path: 'rules/definition.ts', marker: 'imported-rule' },
  ];
  for (const candidates of [sources, sources.toReversed()]) {
    const dates = await ruleIntroductions(root, candidates);
    assert.equal(dates.get('imported')?.introducedAt, '2025-01-02T12:00:00.000Z');
  }
});

void test('shallow histories cannot mislabel the latest edit as a rule introduction', async (t) => {
  const { root, git, commit } = await history(t);
  await writeFile(join(root, 'rule.ts'), 'first\n');
  commit('2025-01-02T12:00:00Z');
  await writeFile(join(root, 'rule.ts'), 'second\n');
  commit('2025-03-04T12:00:00Z');
  const base = git('rev-parse', 'HEAD');
  await writeFile(join(root, 'rule.ts'), 'third\n');
  commit('2025-05-06T12:00:00Z');
  const clone = join(root, 'shallow');
  git('clone', '--quiet', pathToFileURL(root).href, clone);
  git('-C', clone, 'fetch', '--quiet', '--no-tags', 'origin', base);
  assert.equal(git('-C', clone, 'rev-parse', '--is-shallow-repository'), 'false');
  const dates = await ruleIntroductions(clone, [{ id: 'rule', path: 'rule.ts' }]);
  assert.equal(dates.get('rule')?.introducedAt, '2025-01-02T12:00:00.000Z');
  git('-C', clone, 'fetch', '--quiet', '--no-tags', '--depth=1', 'origin', base);
  await assert.rejects(ruleIntroductions(clone, [{ id: 'rule', path: 'rule.ts' }]), /complete Git history/u);
});

void test('a documentation directory cannot silently inherit an ancestor repository', async (t) => {
  const { root, commit } = await history(t);
  await writeFile(join(root, 'rule.ts'), 'rule\n');
  commit('2025-01-02T12:00:00Z');
  const nested = join(root, 'nested');
  await mkdir(nested);
  await assert.rejects(ruleIntroductions(nested, [{ id: 'rule', path: 'rule.ts' }]), /own Git history/u);
});
