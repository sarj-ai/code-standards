import type { BreadcrumbsProps, ReferencePageProps, RulePagerProps } from './contracts';

export interface ComponentDefinition<Props extends object = object> {
  exportPath: string;
  purpose: string;
  properties: Readonly<Record<keyof Props, string>>;
}

export interface ThemeTokenDefinition {
  cssName: `--sarj-${string}`;
  purpose: string;
  light: `#${string}`;
  dark: `#${string}`;
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
    purpose: 'Render a Starlight reference shell with explicit robots behavior.',
    properties: {
      title: 'Document title and primary accessible page identity.',
      description: 'Concise page description used by document metadata.',
      sidebar: 'Starlight sidebar definition for this reference surface.',
      indexable: 'Whether robots may index the public page; defaults to true.',
      hasSidebar: 'Whether the Starlight sidebar is rendered; defaults to true.',
      template: 'Starlight document or splash template; defaults to doc.',
    },
  } satisfies ComponentDefinition<ReferencePageProps>,
  RulePager: {
    exportPath: '@sarj/docs-ui/RulePager.astro',
    purpose: 'Navigate between adjacent rules with accessible links and guarded arrow-key shortcuts.',
    properties: {
      previous: 'Optional previous rule link and label.',
      next: 'Optional next rule link and label.',
    },
  } satisfies ComponentDefinition<RulePagerProps>,
});

export const themeTokenCatalog = Object.freeze([
  { cssName: '--sarj-color-report', purpose: 'Diagnostic and rejection emphasis.', light: '#c34453', dark: '#ff8794' },
  { cssName: '--sarj-color-pass', purpose: 'Accepted example and success emphasis.', light: '#16806d', dark: '#62d5bd' },
  { cssName: '--sarj-color-warning', purpose: 'Warning-level diagnostic emphasis with AA text contrast.', light: '#986a00', dark: '#a97708' },
  { cssName: '--sarj-color-rule', purpose: 'Structural borders and separators.', light: '#e4e6eb', dark: '#272a32' },
  { cssName: '--sarj-color-paper', purpose: 'Reference surface background.', light: '#ffffff', dark: '#0b0c10' },
  { cssName: '--sarj-color-ink', purpose: 'Primary reference text.', light: '#12141a', dark: '#f4f5f8' },
] satisfies readonly ThemeTokenDefinition[]);
