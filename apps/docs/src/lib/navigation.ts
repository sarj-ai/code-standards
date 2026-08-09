import { ENGINES, catalog, engineLabel, type Engine } from './catalog';

export const referenceSidebar = [
  { label: 'Overview', link: '/' },
  { label: 'Use Standards', link: '/cli/' },
  {
    label: `Rules · ${catalog.rules.length}`,
    items: [
      { label: 'All rules', link: '/rules/' },
      ...ENGINES.filter((engine) => catalog.rules.some((rule) => rule.engine === engine)).map((engine) => ({
        label: `${engineLabel(engine)} · ${catalog.rules.filter((rule) => rule.engine === engine).length}`,
        link: `/rules/${engine}/`,
      })),
    ],
  },
  { label: 'Catalog API', link: '/api/' },
];

export function familySidebar(engine: Engine) {
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
