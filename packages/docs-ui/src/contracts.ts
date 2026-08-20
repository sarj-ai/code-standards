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

export type ReferenceSidebar = NonNullable<StarlightUserConfig['sidebar']>;

/**
 * Legacy discovery shorthand. `unlisted` affects search and robots metadata;
 * it is not access control and the rendered page remains public.
 */
export type ReferenceDiscovery = 'searchable' | 'navigation-only' | 'unlisted';

/** Public properties accepted by {@link ReferencePage}. */
export interface ReferencePageProps {
  title: string;
  description: string;
  sidebar: ReferenceSidebar;
  /** Include the page body in Pagefind. Defaults to true. */
  searchable?: boolean;
  /** Allow search engines to index the page. Defaults to true. */
  indexable?: boolean;
  /** @deprecated Prefer the explicit `searchable` and `indexable` properties. */
  discovery?: ReferenceDiscovery;
  hasSidebar?: boolean;
  template?: 'doc' | 'splash';
}
