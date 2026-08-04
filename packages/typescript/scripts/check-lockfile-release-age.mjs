import { readFile } from "node:fs/promises";

const DAY_MS = 24 * 60 * 60 * 1000;
const lockfilePath = process.argv[2] ?? "package-lock.json";
const minimumDays = Number.parseInt(process.env.MIN_RELEASE_AGE_DAYS ?? "14", 10);
const exclusions = new Set(
  (process.env.MIN_RELEASE_AGE_EXCLUDE ?? "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean),
);

if (!Number.isFinite(minimumDays) || minimumDays < 0) {
  throw new Error("MIN_RELEASE_AGE_DAYS must be a non-negative integer");
}

const lock = JSON.parse(await readFile(lockfilePath, "utf8"));
const identities = new Map();

for (const [path, metadata] of Object.entries(lock.packages ?? {})) {
  if (!path.includes("node_modules/") || !metadata.version) continue;
  if (metadata.resolved && !metadata.resolved.startsWith("https://registry.npmjs.org/")) continue;

  const tail = path.slice(path.lastIndexOf("node_modules/") + "node_modules/".length);
  const parts = tail.split("/");
  const name = parts[0].startsWith("@") ? `${parts[0]}/${parts[1]}` : parts[0];
  if (!name || exclusions.has(name) || exclusions.has(`${name}@${metadata.version}`)) continue;
  identities.set(`${name}@${metadata.version}`, { name, version: metadata.version });
}

const entries = [...identities.values()];
const failures = [];
const cutoff = Date.now() - minimumDays * DAY_MS;
let cursor = 0;

async function checkPackages() {
  while (cursor < entries.length) {
    const { name, version } = entries[cursor++];
    const url = `https://registry.npmjs.org/${encodeURIComponent(name)}`;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`npm registry returned ${response.status} for ${name}`);
    const packument = await response.json();
    const publishedAt = packument.time?.[version];
    if (!publishedAt) {
      failures.push(`${name}@${version}: publication time unavailable`);
      continue;
    }
    const age = Date.parse(publishedAt);
    if (!Number.isFinite(age) || age > cutoff) {
      const ageDays = Number.isFinite(age) ? ((Date.now() - age) / DAY_MS).toFixed(1) : "unknown";
      failures.push(`${name}@${version}: ${ageDays} days old`);
    }
  }
}

await Promise.all(Array.from({ length: Math.min(12, entries.length) }, checkPackages));

if (failures.length > 0) {
  console.error(`Lockfile contains packages newer than ${minimumDays} days:`);
  for (const failure of failures.sort()) console.error(`- ${failure}`);
  process.exitCode = 1;
} else {
  console.log(`Verified ${entries.length} locked registry packages are at least ${minimumDays} days old.`);
}
