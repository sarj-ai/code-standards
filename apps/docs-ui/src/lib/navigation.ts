import type { ReferenceSidebar } from '@sarj/docs-ui/contracts';

export const sidebar = [
  { label: 'About', link: '/' },
  { label: 'Components', link: '/components/' },
] as const satisfies ReferenceSidebar;
