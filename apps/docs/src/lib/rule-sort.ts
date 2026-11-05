import { z } from 'zod';

const RuleSortSchema = z.enum(['name', 'newest', 'oldest']).catch('name');
export type RuleSort = z.infer<typeof RuleSortSchema>;

export interface RuleSortKey {
  readonly name: string;
  readonly key: string;
  readonly introducedAt: string | null;
}

export function ruleSort(value: string | null): RuleSort {
  return RuleSortSchema.parse(value);
}

export function compareRules(left: RuleSortKey, right: RuleSortKey, order: RuleSort): number {
  if (order !== 'name') {
    if (left.introducedAt === null && right.introducedAt !== null) return 1;
    if (left.introducedAt !== null && right.introducedAt === null) return -1;
    const dates = (left.introducedAt ?? '').localeCompare(right.introducedAt ?? '', 'en');
    if (dates !== 0) return order === 'newest' ? -dates : dates;
  }
  const names = left.name.localeCompare(right.name, 'en');
  return names === 0 ? left.key.localeCompare(right.key, 'en') : names;
}
