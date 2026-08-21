import sitemap from '@astrojs/sitemap';
import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';
import { URL } from 'node:url';

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
        "default-src 'none'",
        "font-src 'self'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "img-src 'self' data:",
        "object-src 'none'",
      ],
      scriptDirective: {
        resources: [
          { resource: "'self'", kind: 'element' },
        ],
      },
      styleDirective: {
        resources: [{ resource: "'unsafe-inline'", kind: 'attribute' }],
      },
    },
  },
  integrations: [
    sitemap({ filter: (page) => new URL(page).pathname !== '/about/' }),
    starlight({
      title: 'Sarj Standards',
      description: 'Deterministic code standards, diagnostics, and remediation.',
      favicon: '/sarj-logo-light.png',
      logo: {
        alt: 'Sarj',
        dark: './public/sarj-logo-dark.png',
        light: './public/sarj-logo-light.png',
        replacesTitle: true,
      },
      disable404Route: true,
      customCss: ['@sarj/docs-ui/starlight.css', './src/styles/global.css'],
      sidebar: [
        { label: 'About', link: '/' },
        { label: 'Rules', link: '/rules/' },
        { label: 'CLI', link: '/cli/' },
      ],
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/sarj-ai/code-standards' },
      ],
      pagefind: false,
      tableOfContents: false,
      credits: false,
      components: {
        PageTitle: '@sarj/docs-ui/PageAnchor.astro',
        Search: './src/components/NoSearch.astro',
      },
    }),
    cloudflareArtifacts(),
  ],
});
