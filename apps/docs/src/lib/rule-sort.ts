export type RuleSort = 'name' | 'newest' | 'oldest';

export interface RuleSortKey {
  readonly name: string;
  readonly key: string;
  readonly introducedAt: string | null;
}

export function ruleSort(value: string | null): RuleSort {
  return value === 'newest' || value === 'oldest' ? value : 'name';
}

export function compareRules(left: RuleSortKey, right: RuleSortKey, order: RuleSort): number {
  if (order !== 'name') {
    if (left.introducedAt === null && right.introducedAt !== null) return 1;
    if (left.introducedAt !== null && right.introducedAt === null) return -1;
    const dates = (left.introducedAt ?? '').localeCompare(right.introducedAt ?? '', 'en');
    if (dates !== 0) return order === 'newest' ? -dates : dates;
  }
  return left.name.localeCompare(right.name, 'en') || left.key.localeCompare(right.key, 'en');
}
