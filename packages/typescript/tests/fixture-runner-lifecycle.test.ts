import { afterAll, expect, test as baseTest } from "vitest";

const CREATED: string[] = [];
const CLOSED: string[] = [];

const FIXTURE_TEST = baseTest.extend<{ resource: { id: string; values: string[] } }>({
  resource: async ({ task }, use) => {
    const resource = { id: task.id, values: [] as string[] };
    CREATED.push(resource.id);
    try {
      await use(resource);
    } finally {
      CLOSED.push(resource.id);
    }
  },
}).extend("counter", () => ({ value: 0 }));

FIXTURE_TEST("keeps mutations inside the requesting test", ({ resource, counter }) => {
  expect(resource.values).toEqual([]);
  expect(counter.value).toBe(0);
  resource.values.push("first");
  counter.value += 1;
  expect(resource.values).toEqual(["first"]);
  expect(counter.value).toBe(1);
});

FIXTURE_TEST("receives fresh fixture state independently", ({ resource, counter }) => {
  expect(resource.values).toEqual([]);
  expect(counter.value).toBe(0);
});

afterAll(() => {
  expect(CREATED).toHaveLength(2);
  expect(new Set(CREATED).size).toBe(2);
  expect(new Set(CLOSED)).toEqual(new Set(CREATED));
});
