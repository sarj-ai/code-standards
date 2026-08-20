import type { BreadcrumbsProps, ReferencePageProps } from './contracts';

export interface ComponentDefinition<Props extends object = object> {
  exportPath: string;
  purpose: string;
  properties: Readonly<Record<keyof Props, string>>;
}

export interface ThemeTokenDefinition {
  cssName: `--sarj-${string}`;
  purpose: string;
}

export const componentCatalog = Object.freeze({
  Breadcrumbs: {
    exportPath: '@sarj/docs-ui/Breadcrumbs.astro',
    purpose: 'Show a compact, accessible path to the current reference page.',
    properties: {
      ancestors: 'Ordered links from the reference root to the current page.',
      current: 'Current page label, announced with aria-current="page".',
    },
  } satisfies ComponentDefinition<BreadcrumbsProps>,
  PageAnchor: {
    exportPath: '@sarj/docs-ui/PageAnchor.astro',
    purpose: 'Provide the focusable top anchor used by Starlight reference pages.',
    properties: {},
  } satisfies ComponentDefinition,
  ReferencePage: {
    exportPath: '@sarj/docs-ui/ReferencePage.astro',
    purpose: 'Render a Starlight reference shell with explicit search and robots behavior.',
    properties: {
      title: 'Document title and primary accessible page identity.',
      description: 'Concise page description used by document metadata.',
      sidebar: 'Starlight sidebar definition for this reference surface.',
      searchable: 'Whether Pagefind indexes the page body; defaults to true.',
      indexable: 'Whether robots may index the public page; defaults to true.',
      discovery: 'Deprecated shorthand retained for compatibility; never access control.',
      hasSidebar: 'Whether the Starlight sidebar is rendered; defaults to true.',
      template: 'Starlight document or splash template; defaults to doc.',
    },
  } satisfies ComponentDefinition<ReferencePageProps>,
});

export const themeTokenCatalog = Object.freeze([
  { cssName: '--sarj-color-report', purpose: 'Diagnostic and rejection emphasis.' },
  { cssName: '--sarj-color-pass', purpose: 'Accepted example and success emphasis.' },
  { cssName: '--sarj-color-warning', purpose: 'Warning-level diagnostic emphasis with AA text contrast.' },
  { cssName: '--sarj-color-rule', purpose: 'Structural borders and separators.' },
  { cssName: '--sarj-color-paper', purpose: 'Reference surface background.' },
  { cssName: '--sarj-color-ink', purpose: 'Primary reference text.' },
] satisfies readonly ThemeTokenDefinition[]);
