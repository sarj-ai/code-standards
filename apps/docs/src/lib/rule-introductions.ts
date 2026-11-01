import { execFile } from 'node:child_process';
import { realpath } from 'node:fs/promises';
import { promisify } from 'node:util';

const git = promisify(execFile);

export interface RuleHistorySource {
  readonly id: string;
  readonly path: string;
  readonly marker?: string;
}

export interface RuleIntroduction {
  readonly introducedAt: string;
  readonly commit: string;
}

export async function ruleIntroductions(
  repositoryDirectory: string,
  sources: readonly RuleHistorySource[],
): Promise<ReadonlyMap<string, RuleIntroduction | null>> {
  const options = {
    cwd: repositoryDirectory,
    encoding: 'utf8' as const,
    timeout: 30_000,
    maxBuffer: 1024 * 1024,
  };
  const [{ stdout: root }, { stdout: shallow }] = await Promise.all([
    git('git', ['rev-parse', '--show-toplevel'], options),
    git('git', ['rev-parse', '--is-shallow-repository'], options),
  ]);
  if (await realpath(root.trim()) !== await realpath(repositoryDirectory)) {
    throw new Error('Rule introduction dates must use the documentation repository’s own Git history.');
  }
  if (shallow.trim() !== 'false') {
    throw new Error('Rule introduction dates require complete Git history; use checkout fetch-depth: 0.');
  }

  const result = new Map<string, RuleIntroduction | null>();
  const pending = sources.values();
  await Promise.all(Array.from({ length: Math.min(4, sources.length) }, async () => {
    for (const source of pending) {
      const selection = source.marker === undefined ? ['--diff-filter=A'] : ['-S', source.marker];
      const { stdout, stderr } = await git('git', [
        'log', '--first-parent', '--follow', '--find-renames', '--format=%H %ct',
        ...selection, '--', source.path,
      ], options);
      if (stderr.trim()) throw new Error(`Incomplete introduction history for ${source.id}: ${stderr.trim()}`);
      const first = stdout.trim().split('\n').at(-1);
      if (!first) {
        if (!result.has(source.id)) result.set(source.id, null);
        continue;
      }
      const match = /^([a-f0-9]{40}) (\d+)$/u.exec(first);
      const commit = match?.at(1);
      const timestamp = match?.at(2);
      if (commit === undefined || timestamp === undefined) throw new Error(`Invalid introduction history for ${source.id}.`);
      const candidate = {
        commit,
        introducedAt: new Date(Number(timestamp) * 1000).toISOString(),
      };
      const previous = result.get(source.id);
      if (!previous || candidate.introducedAt < previous.introducedAt ||
        (candidate.introducedAt === previous.introducedAt && candidate.commit < previous.commit)) {
        result.set(source.id, candidate);
      }
    }
  }));
  return result;
}
