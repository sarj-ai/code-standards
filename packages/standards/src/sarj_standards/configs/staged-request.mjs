// Run against the selected Git index without changing the consumer worktree.
import { execFileSync } from "node:child_process";
// eslint-disable-next-line @sarj/prefer-node-fs-promises -- This short-lived adapter performs a bounded synchronous scan and then exits.
import { existsSync, symlinkSync } from "node:fs";
import { isAbsolute, join, relative, resolve, sep } from "node:path";

export function stagedRequest(request, temporary) {
  const original = request.repositoryRoot;
  const snapshot = join(temporary, "index");
  const gitDirectory = execFileSync("git", ["rev-parse", "--absolute-git-dir"], {
    cwd: original,
    encoding: "utf8",
  }).trim();
  execFileSync("git", ["checkout-index", "--all", `--prefix=${snapshot}/`], {
    cwd: original,
    maxBuffer: 16 * 1024 * 1024,
  });
  const mapped = (path) => {
    const child = relative(original, path);
    if (isAbsolute(child) || child === ".." || child.startsWith(`..${sep}`)) return path;
    return resolve(snapshot, child);
  };
  // Runtime dependencies remain installed in the original checkout. Git never
  // copies ignored node_modules directories into the source snapshot.
  for (const root of new Set([
    original,
    request.installRoot,
    ...request.projects.map((project) => project.root),
  ])) {
    const modules = join(root, "node_modules");
    const target = mapped(modules);
    if (existsSync(modules) && !existsSync(target)) symlinkSync(modules, target, "junction");
  }
  request.repositoryRoot = snapshot;
  request.config = mapped(request.config);
  request.paths = request.paths.map(mapped);
  request.metadataPaths = (request.metadataPaths ?? []).map(mapped);
  request.excludedDirectories = (request.excludedDirectories ?? []).map(mapped);
  request.projects = request.projects.map((project) => ({
    ...project,
    root: mapped(project.root),
    excluded: project.excluded.map(mapped),
  }));
  process.env.GIT_DIR = gitDirectory;
  process.env.GIT_WORK_TREE = snapshot;
  return (path) => resolve(original, relative(snapshot, path));
}
