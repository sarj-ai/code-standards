import type { StarlightUserConfig } from '@astrojs/starlight/types';

import { ENGINES, catalog, engineLabel, type Engine } from './catalog';

export type Sidebar = NonNullable<StarlightUserConfig['sidebar']>;

export const referenceSidebar = Object.freeze([
  { label: 'Overview', link: '/' },
  { label: 'Use Standards', link: '/cli/' },
  {
    label: `Rules · ${String(catalog.rules.length)}`,
    items: [
      { label: 'All rules', link: '/rules/' },
      ...ENGINES.filter((engine) => catalog.rules.some((rule) => rule.engine === engine)).map((engine) => ({
        label: `${engineLabel(engine)} · ${String(catalog.rules.filter((rule) => rule.engine === engine).length)}`,
        link: `/rules/${engine}/`,
      })),
    ],
  },
  { label: 'Catalog API', link: '/api/' },
] satisfies Sidebar);

export function familySidebar(engine: Engine): Sidebar {
  return [
    ...referenceSidebar,
    {
      label: engineLabel(engine),
      items: catalog.rules
        .filter((rule) => rule.engine === engine)
        .map((rule) => ({ label: rule.id, link: `/rules/${engine}/${rule.id}/` })),
    },
  ];
}
