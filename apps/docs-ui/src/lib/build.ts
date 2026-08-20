// These host-provided values are build provenance, not application configuration.
// eslint-disable-next-line @sarj/no-raw-env -- Cloudflare/GitHub inject immutable build metadata.
export const sourceRevision = process.env.WORKERS_CI_COMMIT_SHA
  // eslint-disable-next-line @sarj/no-raw-env -- local GitHub builds use the standard fallback marker.
  ?? process.env.GITHUB_SHA
  ?? 'local';
