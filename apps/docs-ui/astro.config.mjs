import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';

import cloudflareArtifacts from './src/integrations/cloudflare-artifacts.ts';

export default defineConfig({
  site: 'https://docs-ui.sarj.ai',
  output: 'static',
  trailingSlash: 'always',
  compressHTML: true,
  markdown: { syntaxHighlight: 'prism' },
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
      scriptDirective: { resources: [{ resource: "'self'", kind: 'element' }] },
      styleDirective: { resources: [{ resource: "'unsafe-inline'", kind: 'attribute' }] },
    },
  },
  integrations: [
    starlight({
      title: '@sarj/docs-ui',
      description: 'Live components and tokens from the shared Sarj documentation UI package.',
      disable404Route: true,
      customCss: ['@sarj/docs-ui/starlight.css', './src/styles/global.css'],
      sidebar: [],
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/sarj-ai/code-standards/tree/main/packages/docs-ui' }],
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
