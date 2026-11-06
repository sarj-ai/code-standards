import { z } from "zod";

const SearchIndexSchema = z.object({
  entries: z.array(z.object({
    anchor: z.string(),
    displayId: z.string(),
    family: z.string().nullable(),
    href: z.string(),
    summary: z.string(),
  })),
});

export function parseSearchIndex(value: unknown) {
  return SearchIndexSchema.parse(value).entries.map((entry) => ({
    ...entry,
    searchText: [entry.displayId, entry.summary, entry.family]
      .filter((part) => part !== null)
      .join(" ")
      .toLocaleLowerCase("en-US"),
  }));
}
