export function normalizeRuleSearch(value: string): string {
  return value
    .toLowerCase()
    .replaceAll(/[-_/]+/gu, " ")
    .replaceAll(/\s+/gu, " ")
    .trim();
}

export function matchesRuleSearch(text: string, query: string): boolean {
  return normalizeRuleSearch(query)
    .split(" ")
    .every((term) => text.includes(term));
}
