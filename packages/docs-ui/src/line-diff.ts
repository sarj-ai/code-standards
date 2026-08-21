import { diffLines } from 'diff';

import type { CodeLineMark } from './contracts';

export interface ChangedLineMarks {
  before: CodeLineMark | undefined;
  after: CodeLineMark | undefined;
}

/** Return presentation-only line markers for two explicitly related sources. */
export function changedLineMarks(before: string, after: string): ChangedLineMarks {
  const beforeLines: number[] = [];
  const afterLines: number[] = [];
  let beforeLine = 1;
  let afterLine = 1;

  for (const change of diffLines(before, after)) {
    const count = change.count;
    if (change.removed) {
      addLines(beforeLines, beforeLine, count);
      beforeLine += count;
    } else if (change.added) {
      addLines(afterLines, afterLine, count);
      afterLine += count;
    } else {
      beforeLine += count;
      afterLine += count;
    }
  }

  return { before: lineMark(beforeLines), after: lineMark(afterLines) };
}

function addLines(output: number[], first: number, count: number): void {
  for (let offset = 0; offset < count; offset += 1) output.push(first + offset);
}

function lineMark(lines: readonly number[]): CodeLineMark | undefined {
  if (lines.length === 0) return undefined;
  const ranges: string[] = [];
  let first = lines[0] ?? 1;
  let last = first;

  for (const line of lines.slice(1)) {
    if (line === last + 1) {
      last = line;
      continue;
    }
    ranges.push(first === last ? String(first) : `${String(first)}-${String(last)}`);
    first = line;
    last = line;
  }
  ranges.push(first === last ? String(first) : `${String(first)}-${String(last)}`);
  return { range: ranges.join(',') };
}
