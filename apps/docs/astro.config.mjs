import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';

import cloudflareArtifacts from './src/integrations/cloudflare-artifacts.ts';

export default defineConfig({
  site: 'https://code-standards.sarj.ai',
  output: 'static',
  trailingSlash: 'always',
  compressHTML: true,
  markdown: {
    syntaxHighlight: 'prism',
  },
  security: {
    csp: {
      directives: [
        "base-uri 'self'",
        "connect-src 'self'",
        "font-src 'self'",
        "form-action 'self'",
        "img-src 'self' data:",
        "object-src 'none'",
      ],
      styleDirective: {
        resources: [{ resource: "'unsafe-inline'", kind: 'attribute' }],
      },
    },
  },
  integrations: [
    starlight({
      title: 'Sarj Standards',
      description: 'Deterministic code standards, diagnostics, and remediation.',
      favicon: '/favicon.svg',
      disable404Route: true,
      customCss: ['./src/styles/global.css'],
      sidebar: [
        { label: 'Overview', link: '/' },
        { label: 'CLI', link: '/cli/' },
        { label: 'Rules', link: '/rules/' },
        { label: 'Catalog API', link: '/api/' },
      ],
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/sarj-ai/standards' },
      ],
      pagefind: true,
      tableOfContents: false,
      credits: false,
      components: {
        PageTitle: './src/components/ReferencePageTitle.astro',
      },
    }),
    cloudflareArtifacts(),
  ],
});
