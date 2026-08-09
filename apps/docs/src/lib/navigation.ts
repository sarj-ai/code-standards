import type { StarlightUserConfig } from '@astrojs/starlight/types';

import { ENGINES, catalog, engineLabel } from './catalog';

export type Sidebar = NonNullable<StarlightUserConfig['sidebar']>;

export const referenceSidebar = Object.freeze([
  { label: 'Rules', link: '/' },
  { label: 'CLI', link: '/cli/' },
  {
    label: `Languages · ${String(catalog.rules.length)}`,
    items: [
      ...ENGINES.filter((engine) => catalog.rules.some((rule) => rule.engine === engine)).map((engine) => ({
        label: `${engineLabel(engine)} · ${String(catalog.rules.filter((rule) => rule.engine === engine).length)}`,
        link: `/rules/${engine}/`,
      })),
    ],
  },
] satisfies Sidebar);
