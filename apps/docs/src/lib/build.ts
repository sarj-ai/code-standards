export const sourceRevision = process.env.WORKERS_CI_COMMIT_SHA ?? process.env.GITHUB_SHA ?? 'local';
