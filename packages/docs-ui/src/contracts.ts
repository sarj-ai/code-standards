import type { StarlightUserConfig } from '@astrojs/starlight/types';

/** One navigable ancestor rendered before the current page. */
export interface BreadcrumbAncestor {
  label: string;
  href: string;
}

/** Public properties accepted by {@link Breadcrumbs}. */
export interface BreadcrumbsProps {
  ancestors: readonly BreadcrumbAncestor[];
  current: string;
}

export interface RulePagerLink {
  href: string;
  label: string;
}

/** Public properties accepted by {@link RulePager}. */
export interface RulePagerProps {
  previous?: RulePagerLink | null;
  next?: RulePagerLink | null;
}

export type ReferenceSidebar = NonNullable<StarlightUserConfig['sidebar']>;

/** Public properties accepted by {@link ReferencePage}. */
export interface ReferencePageProps {
  title: string;
  description: string;
  sidebar: ReferenceSidebar;
  /** Allow search engines to index the page. Defaults to true. */
  indexable?: boolean;
  hasSidebar?: boolean;
  template?: 'doc' | 'splash';
}
