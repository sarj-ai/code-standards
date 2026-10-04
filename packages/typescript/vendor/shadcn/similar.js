//#region src/grammar/classes.ts
function splitVariants(token) {
	if (!token.includes(":")) return {
		variants: [],
		base: token
	};
	const segments = [];
	let bracketDepth = 0;
	let parenDepth = 0;
	let current = "";
	for (const char of token) {
		if (char === "[") bracketDepth++;
		else if (char === "]") bracketDepth--;
		else if (bracketDepth === 0) {
			if (char === "(") parenDepth++;
			else if (char === ")") parenDepth--;
		}
		if (char === ":" && bracketDepth === 0 && parenDepth === 0) {
			segments.push(current);
			current = "";
			continue;
		}
		current += char;
	}
	segments.push(current);
	return {
		variants: segments.slice(0, -1),
		base: segments[segments.length - 1]
	};
}
function splitClasses(value) {
	return value.split(/\s+/).filter(Boolean);
}
const MARKERS = /* @__PURE__ */ new Set([
	"group",
	"peer",
	"dark",
	"light"
]);
function isMarkerClass(token) {
	return MARKERS.has(normalizeClass(token).split("/")[0]);
}
function normalizeClass(token) {
	const { base } = splitVariants(token);
	return base.replace(/^!/, "").replace(/!$/, "").replace(/^-/, "");
}
function isArbitraryValue(token) {
	if (!token.includes("[")) return false;
	const { base } = splitVariants(token);
	return /-\[[^\]]*\]/.test(base) || /^\[[^\]]+:[^\]]+\]$/.test(base);
}
const COLOR_PREFIX = /^(?:text-shadow|inset-shadow|inset-ring|drop-shadow|scrollbar-(?:thumb|track)|ring-offset|border(?:-[trblxyse]|-[bi][se])?|divide(?:-[xy])?|mask-(?:linear|radial|conic|[trblxy])-(?:from|to)|bg|text|ring|outline|fill|stroke|from|via|to|accent|caret|decoration|placeholder|shadow)-/;
const PALETTE = [
	"slate",
	"gray",
	"zinc",
	"neutral",
	"stone",
	"mauve",
	"olive",
	"mist",
	"taupe",
	"red",
	"orange",
	"amber",
	"yellow",
	"lime",
	"green",
	"emerald",
	"teal",
	"cyan",
	"sky",
	"blue",
	"indigo",
	"violet",
	"purple",
	"fuchsia",
	"pink",
	"rose"
];
const OPACITY_MODIFIER = /\/(?:[\w.%]+|\[[^\]]*\]|\([^)]*\))$/;
const PALETTE_RE = new RegExp(`${COLOR_PREFIX.source}(?:${PALETTE.join("|")})-\\d{2,3}(?:${OPACITY_MODIFIER.source})?$`);
function isPaletteClass(token) {
	return PALETTE_RE.test(normalizeClass(token));
}
function withBase(token, base) {
	const { variants, base: original } = splitVariants(token);
	const leadingBang = original.startsWith("!") ? "!" : "";
	const trailingBang = !leadingBang && original.endsWith("!") ? "!" : "";
	const negative = original.replace(/^!/, "").replace(/!$/, "").startsWith("-") ? "-" : "";
	return `${variants.length ? `${variants.join(":")}:` : ""}${leadingBang}${negative}${base}${trailingBang}`;
}
function replaceClass(value, token, replacement) {
	const escaped = token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
	return value.replace(new RegExp(`(^|\\s)${escaped}(?=\\s|$)`), (_, lead) => `${lead}${replacement}`);
}

//#endregion
//#region src/grammar/similar.ts
function editDistance(a, b) {
	const rows = a.length + 1;
	const cols = b.length + 1;
	const d = Array.from({ length: rows }, (_, i) => {
		const row = new Array(cols).fill(0);
		row[0] = i;
		return row;
	});
	for (let j = 0; j < cols; j++) d[0][j] = j;
	for (let i = 1; i < rows; i++) for (let j = 1; j < cols; j++) {
		const cost = a[i - 1] === b[j - 1] ? 0 : 1;
		d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost);
		if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + 1);
	}
	return d[rows - 1][cols - 1];
}
function didYouMean(value, candidates, budget = value.length < 6 ? 1 : 2) {
	if (value.length < 3) return null;
	let best = null;
	for (const name of candidates) {
		if (name === value) return null;
		if (Math.abs(name.length - value.length) > budget) continue;
		const distance = editDistance(value, name);
		if (distance > budget) continue;
		if (!best || distance < best.distance || distance === best.distance && name.localeCompare(best.name) < 0) best = {
			name,
			distance
		};
	}
	return best?.name ?? null;
}

//#endregion
export { isArbitraryValue as a, normalizeClass as c, splitVariants as d, withBase as f, OPACITY_MODIFIER as i, replaceClass as l, editDistance as n, isMarkerClass as o, COLOR_PREFIX as r, isPaletteClass as s, didYouMean as t, splitClasses as u };