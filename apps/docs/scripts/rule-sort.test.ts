import assert from 'node:assert/strict';
import test from 'node:test';

import { compareRules, ruleSort } from '../src/lib/rule-sort.ts';

const rules = [
  { key: 'unknown', name: 'A', introducedAt: null },
  { key: 'old', name: 'B', introducedAt: '2025-01-01T00:00:00.000Z' },
  { key: 'new-b', name: 'C', introducedAt: '2026-01-01T00:00:00.000Z' },
  { key: 'new-a', name: 'C', introducedAt: '2026-01-01T00:00:00.000Z' },
];

for (const [order, expected] of [
  ['newest', ['new-a', 'new-b', 'old', 'unknown']],
  ['oldest', ['old', 'new-a', 'new-b', 'unknown']],
  ['name', ['unknown', 'old', 'new-a', 'new-b']],
] as const) {
  void test(`sort ${order} has deterministic ties and date fallbacks`, () => {
    assert.deepEqual(rules.toSorted((left, right) => compareRules(left, right, order)).map((rule) => rule.key), expected);
  });
}

void test('shared links accept supported date orders and safely normalize unknown query values', () => {
  assert.equal(ruleSort('newest'), 'newest');
  assert.equal(ruleSort('oldest'), 'oldest');
  assert.equal(ruleSort(null), 'name');
  assert.equal(ruleSort('unsupported'), 'name');
});
