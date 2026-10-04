import { z } from "zod";

const SearchIndexSchema = z.object({
  entries: z.array(
    z.object({
      anchor: z.string(),
      displayId: z.string(),
      family: z.string().nullable(),
      href: z.string(),
      summary: z.string(),
    }),
  ),
});

export async function fetchThirdPartySearchIndex(href: string) {
  const response = await fetch(href);
  if (!response.ok) {
    throw new Error(`Search index returned ${String(response.status)}.`);
  }
  return SearchIndexSchema.parse(await response.json()).entries;
}
