import type { StarlightUserConfig } from "@astrojs/starlight/types";

import { ENGINES, catalog, engineLabel } from "./catalog";
import { thirdPartyCatalog } from "./third-party-catalog";

export type Sidebar = NonNullable<StarlightUserConfig["sidebar"]>;

export const referenceSidebar = Object.freeze([
  { label: "About", link: "/" },
  { label: `Rules · ${String(catalog.rules.length)}`, link: "/rules/" },
  ...ENGINES.filter((engine) =>
    catalog.rules.some((rule) => rule.engine === engine),
  ).map((engine) => ({
    label: `${engineLabel(engine)} · ${String(catalog.rules.filter((rule) => rule.engine === engine).length)}`,
    link: `/rules/${engine}/`,
    attrs: { class: "sidebar-engine-link" },
  })),
  {
    label: `Third-party linters · ${String(thirdPartyCatalog.rules.length)}`,
    link: "/third-party-linters/",
  },
  { label: "CLI", link: "/cli/" },
] satisfies Sidebar);
