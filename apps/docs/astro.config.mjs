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
      scriptDirective: {
        resources: [
          { resource: "'self'", kind: 'element' },
          { resource: "'self'", kind: 'default' },
          { resource: "'wasm-unsafe-eval'", kind: 'default' },
        ],
      },
      styleDirective: {
        resources: [{ resource: "'unsafe-inline'", kind: 'attribute' }],
      },
    },
  },
  integrations: [
    starlight({
      title: 'Sarj Standards',
      description: 'Deterministic code standards, diagnostics, and remediation.',
      favicon: '/sarj-logo-light.png',
      disable404Route: true,
      customCss: ['@sarj/docs-ui/styles.css', './src/styles/global.css'],
      sidebar: [
        { label: 'About', link: '/' },
        { label: 'Rules', link: '/rules/' },
        { label: 'CLI', link: '/cli/' },
      ],
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/sarj-ai/standards' },
      ],
      pagefind: true,
      tableOfContents: false,
      credits: false,
      components: {
        PageTitle: '@sarj/docs-ui/PageAnchor.astro',
      },
    }),
    cloudflareArtifacts(),
  ],
});
