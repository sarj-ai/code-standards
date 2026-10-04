import { d as splitVariants, t as didYouMean } from "./similar.js";
import { createRequire } from "node:module";
import * as fs from "node:fs";
import * as path from "node:path";
import { workerData } from "node:worker_threads";
import { pathToFileURL } from "node:url";

//#region src/tailwind/oracle.ts
const SIGNATURE_TTL = 1e3;
const loaded = /* @__PURE__ */ new Map();
let generations = 0;
function resolveFrom(base, id) {
	return createRequire(path.join(base, "noop.js")).resolve(id);
}
async function loadTailwind(dir) {
	for (const from of [dir, process.cwd()]) {
		let resolved;
		try {
			resolved = resolveFrom(from, "tailwindcss");
		} catch {
			continue;
		}
		const mod = await import(pathToFileURL(resolved).href);
		const api = typeof mod.__unstable__loadDesignSystem === "function" ? mod : typeof mod.default?.__unstable__loadDesignSystem === "function" ? mod.default : null;
		if (api) return api;
		throw new Error(`${resolved} is not Tailwind v4 (no __unstable__loadDesignSystem)`);
	}
	return null;
}
function existingFile(candidate) {
	try {
		return fs.statSync(candidate).isFile() ? candidate : null;
	} catch {
		return null;
	}
}
function stylesheetAt(dir, name) {
	const base = path.join(dir, name);
	return existingFile(base) ?? existingFile(`${base}.css`) ?? existingFile(path.join(base, "index.css"));
}
function styleTarget(entry) {
	if (typeof entry === "string") return entry;
	if (!entry || typeof entry !== "object") return null;
	const record = entry;
	for (const key of ["style", "default"]) {
		const target = styleTarget(record[key]);
		if (target) return target;
	}
	return null;
}
function exportedStyle(exports, subpath) {
	const exact = styleTarget(exports[`./${subpath}`]);
	if (exact) return exact;
	const patterns = Object.keys(exports).filter((key) => key.startsWith("./") && key.includes("*")).sort((a, b) => b.length - a.length);
	for (const key of patterns) {
		const star = key.indexOf("*");
		const prefix = key.slice(2, star);
		const suffix = key.slice(star + 1);
		if (subpath.length < prefix.length + suffix.length || !subpath.startsWith(prefix) || !subpath.endsWith(suffix)) continue;
		const target = styleTarget(exports[key]);
		if (!target) continue;
		const captured = subpath.slice(prefix.length, subpath.length - suffix.length);
		return target.replaceAll("*", () => captured);
	}
	return null;
}
function packageDirectory(base, name) {
	let dir = base;
	for (let depth = 0; depth < 32; depth++) {
		const candidate = path.join(dir, "node_modules", name);
		if (existingFile(path.join(candidate, "package.json"))) return candidate;
		const parent = path.dirname(dir);
		if (parent === dir) break;
		dir = parent;
	}
	return null;
}
function resolveStylesheet(base, id) {
	if (id === "tailwindcss") return resolveStylesheet(base, "tailwindcss/index.css");
	if (id.startsWith(".") || path.isAbsolute(id)) return stylesheetAt(path.dirname(path.resolve(base, id)), path.basename(id));
	const match = id.match(/^(@[^/]+\/[^/]+|[^/]+)(?:\/(.*))?$/);
	if (!match) return null;
	const [, name, subpath] = match;
	const pkgDir = packageDirectory(base, name);
	if (!pkgDir) return null;
	let pkg = {};
	try {
		pkg = JSON.parse(fs.readFileSync(path.join(pkgDir, "package.json"), "utf-8"));
	} catch {}
	const exports = pkg.exports;
	if (subpath) {
		const target = exports && typeof exports === "object" ? exportedStyle(exports, subpath) : null;
		if (target) return existingFile(path.join(pkgDir, target));
		return stylesheetAt(path.dirname(path.join(pkgDir, subpath)), path.basename(subpath));
	}
	const root = typeof exports === "string" ? exports : exports && typeof exports === "object" ? styleTarget(exports["."] ?? exports) : null;
	for (const target of [
		root,
		pkg.style,
		pkg.main
	]) {
		if (typeof target !== "string") continue;
		const file = existingFile(path.join(pkgDir, target));
		if (file) return file;
	}
	return stylesheetAt(pkgDir, "index");
}
function realpathOf(file) {
	try {
		return fs.realpathSync.native(file);
	} catch {
		return file;
	}
}
function mtimeOf(file) {
	try {
		return fs.statSync(file).mtimeMs;
	} catch {
		return null;
	}
}
function signatureOf(files) {
	return files.map((file) => `${file}:${mtimeOf(file) ?? "missing"}`).join("|");
}
async function build(cssFile) {
	const dir = path.dirname(cssFile);
	const tailwind = await loadTailwind(dir);
	if (!tailwind) throw new Error(`tailwindcss v4 could not be resolved from ${dir}`);
	const files = [cssFile];
	let modules = 0;
	const css = fs.readFileSync(cssFile, "utf-8");
	const ds = await tailwind.__unstable__loadDesignSystem(css, {
		base: dir,
		async loadStylesheet(id, base) {
			if (/^(?:https?:|data:)/.test(id)) return {
				base,
				content: ""
			};
			const resolved = resolveStylesheet(base, id);
			if (!resolved) throw new Error(`@import "${id}" could not be resolved from ${base}`);
			const file = realpathOf(resolved);
			files.push(file);
			return {
				base: path.dirname(file),
				content: fs.readFileSync(file, "utf-8")
			};
		},
		async loadModule(id, base) {
			const resolved = resolveFrom(base, id);
			files.push(resolved);
			modules++;
			const url = pathToFileURL(resolved);
			url.searchParams.set("mtime", String(mtimeOf(resolved)));
			const mod = await import(url.href);
			return {
				base: path.dirname(resolved),
				module: mod.default ?? mod
			};
		}
	});
	const variants = ds.getVariants();
	return {
		ds,
		files,
		modules,
		prefix: ds.theme?.prefix ?? null,
		signature: signatureOf(files),
		checkedAt: Date.now(),
		generation: ++generations,
		classNames: null,
		staticVariants: variants.filter((v) => !v.isArbitrary && !v.values.length).map((v) => v.name),
		functionalVariants: variants.filter((v) => v.isArbitrary || v.values.length).map((v) => v.name)
	};
}
async function designSystemFor(cssFile) {
	const cached = loaded.get(cssFile);
	const now = Date.now();
	if (cached) {
		if (now - cached.checkedAt < SIGNATURE_TTL) return cached;
		if (signatureOf(cached.files) === cached.signature) {
			cached.checkedAt = now;
			return cached;
		}
	}
	const fresh = await build(cssFile);
	loaded.set(cssFile, fresh);
	return fresh;
}
function classNamesOf(system) {
	if (!system.classNames) system.classNames = system.ds.getClassList().map((entry) => Array.isArray(entry) ? entry[0] : entry);
	return system.classNames;
}
function variantKnown(system, variant) {
	const name = variant.replace(/\/.*$/, "");
	if (name.startsWith("[") || name.startsWith("@")) return true;
	if (system.staticVariants.includes(name)) return true;
	return system.functionalVariants.some((prefix) => name === prefix || name.startsWith(`${prefix}-`));
}
function suggestionFor(system, candidate) {
	const { variants, base } = splitVariants(candidate);
	const prefixed = system.prefix !== null && variants[0] === system.prefix;
	const probe = prefixed ? `${system.prefix}:${base}` : base;
	if (variants.length && system.ds.candidatesToCss([probe])[0] !== null) {
		let changed = false;
		const fixed = variants.map((variant, i) => {
			if (prefixed && i === 0) return variant;
			if (variantKnown(system, variant)) return variant;
			const meant = didYouMean(variant, system.staticVariants, 1);
			if (!meant) return variant;
			changed = true;
			return meant;
		});
		return changed ? [...fixed, base].join(":") : null;
	}
	const bare = base.replace(/^!/, "").replace(/!$/, "").replace(/^-/, "");
	const meant = didYouMean(bare, classNamesOf(system));
	if (!meant) return null;
	const rebuilt = base.replace(bare, meant);
	return [...variants, rebuilt].join(":");
}
function baseKnownOf(system, candidate) {
	const { variants, base } = splitVariants(candidate);
	if (!variants.length) return false;
	const bare = system.prefix && variants[0] === system.prefix ? `${system.prefix}:${base}` : base;
	if (variants.length === (bare === base ? 0 : 1)) return false;
	return system.ds.candidatesToCss([bare])[0] !== null;
}
async function query(cssFile, candidates) {
	let system;
	try {
		system = await designSystemFor(cssFile);
	} catch (error) {
		return {
			ok: false,
			reason: error.message
		};
	}
	const css = system.ds.candidatesToCss(candidates);
	const unknown = [];
	for (let i = 0; i < candidates.length; i++) {
		if (css[i] !== null) continue;
		unknown.push({
			token: candidates[i],
			suggestion: suggestionFor(system, candidates[i]),
			baseKnown: baseKnownOf(system, candidates[i])
		});
	}
	return {
		ok: true,
		generation: system.generation,
		hasModules: system.modules > 0,
		unknown
	};
}

//#endregion
//#region src/tailwind/worker.ts
const port = workerData.port;
port.on("message", async ({ id, cssFile, candidates, shared }) => {
	let answer;
	try {
		answer = await query(cssFile, candidates);
	} catch (error) {
		answer = {
			ok: false,
			reason: error.message
		};
	}
	port.postMessage({
		id,
		answer
	});
	const flag = new Int32Array(shared);
	Atomics.store(flag, 0, 1);
	Atomics.notify(flag, 0);
});

//#endregion
export {  };
