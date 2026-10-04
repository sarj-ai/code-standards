import { a as isArbitraryValue$1, c as normalizeClass, d as splitVariants, f as withBase, i as OPACITY_MODIFIER, l as replaceClass, n as editDistance, o as isMarkerClass, r as COLOR_PREFIX, s as isPaletteClass, t as didYouMean, u as splitClasses } from "./similar.js";
import { createRequire } from "node:module";
import * as fs from "node:fs";
import { readFileSync } from "node:fs";
import * as path from "node:path";
import { defaultConfig } from "cn/config";
import { MessageChannel, Worker, receiveMessageOnPort } from "node:worker_threads";

//#region \0rolldown/runtime.js
var __defProp = Object.defineProperty;
var __exportAll = (all, no_symbols) => {
	let target = {};
	for (var name in all) {
		__defProp(target, name, {
			get: all[name],
			enumerable: true
		});
	}
	if (!no_symbols) {
		__defProp(target, Symbol.toStringTag, { value: "Module" });
	}
	return target;
};

//#endregion
//#region src/grammar/categories.ts
const GROUP_CATEGORY = {
	aspect: null,
	container: null,
	"container-type": null,
	"container-named": null,
	contain: null,
	"contain-size": null,
	"contain-layout": null,
	"contain-paint": null,
	"contain-style": null,
	columns: null,
	"break-after": null,
	"break-before": null,
	"break-inside": null,
	"box-decoration": null,
	box: null,
	display: null,
	sr: null,
	float: null,
	clear: null,
	isolation: null,
	"object-fit": null,
	"object-position": null,
	overflow: null,
	"overflow-x": null,
	"overflow-y": null,
	overscroll: null,
	"overscroll-x": null,
	"overscroll-y": null,
	position: null,
	inset: null,
	"inset-x": null,
	"inset-y": null,
	start: null,
	end: null,
	"inset-bs": null,
	"inset-be": null,
	top: null,
	right: null,
	bottom: null,
	left: null,
	visibility: null,
	z: null,
	basis: null,
	"flex-direction": null,
	"flex-wrap": null,
	flex: null,
	grow: null,
	shrink: null,
	order: null,
	"grid-cols": null,
	"col-start-end": null,
	"col-start": null,
	"col-end": null,
	"grid-rows": null,
	"row-start-end": null,
	"row-start": null,
	"row-end": null,
	"grid-flow": null,
	"auto-cols": null,
	"auto-rows": null,
	gap: "spacing",
	"gap-x": "spacing",
	"gap-y": "spacing",
	"justify-content": null,
	"justify-items": null,
	"justify-self": null,
	"align-content": null,
	"align-items": null,
	"align-self": null,
	"place-content": null,
	"place-items": null,
	"place-self": null,
	p: "spacing",
	px: "spacing",
	py: "spacing",
	ps: "spacing",
	pe: "spacing",
	pbs: "spacing",
	pbe: "spacing",
	pt: "spacing",
	pr: "spacing",
	pb: "spacing",
	pl: "spacing",
	m: null,
	mx: null,
	my: null,
	ms: null,
	me: null,
	mbs: null,
	mbe: null,
	mt: null,
	mr: null,
	mb: null,
	ml: null,
	"space-x": "spacing",
	"space-x-reverse": "spacing",
	"space-y": "spacing",
	"space-y-reverse": "spacing",
	size: null,
	"inline-size": null,
	"min-inline-size": null,
	"max-inline-size": null,
	"block-size": null,
	"min-block-size": null,
	"max-block-size": null,
	w: null,
	"min-w": null,
	"max-w": null,
	h: null,
	"min-h": null,
	"max-h": null,
	"font-size": "typography",
	"font-smoothing": "typography",
	"font-style": "typography",
	"font-weight": "typography",
	"font-stretch": "typography",
	"font-family": "typography",
	"font-features": "typography",
	"fvn-normal": "typography",
	"fvn-ordinal": "typography",
	"fvn-slashed-zero": "typography",
	"fvn-figure": "typography",
	"fvn-spacing": "typography",
	"fvn-fraction": "typography",
	tracking: "typography",
	"line-clamp": "typography",
	leading: "typography",
	"list-image": "typography",
	"list-style-position": "typography",
	"list-style-type": "typography",
	"text-alignment": null,
	"placeholder-color": "color",
	"text-color": "color",
	"text-decoration": "typography",
	"text-decoration-style": "typography",
	"text-decoration-thickness": "typography",
	"text-decoration-color": "color",
	"underline-offset": "typography",
	"text-transform": "typography",
	"text-overflow": "typography",
	"text-wrap": "typography",
	indent: "typography",
	"tab-size": null,
	"vertical-align": null,
	whitespace: null,
	break: null,
	wrap: null,
	hyphens: "typography",
	content: null,
	"bg-attachment": "effects",
	"bg-clip": "effects",
	"bg-origin": "effects",
	"bg-position": "effects",
	"bg-repeat": "effects",
	"bg-size": "effects",
	"bg-image": "effects",
	"bg-color": "color",
	"gradient-from-pos": "effects",
	"gradient-via-pos": "effects",
	"gradient-to-pos": "effects",
	"gradient-from": "color",
	"gradient-via": "color",
	"gradient-to": "color",
	rounded: "shape",
	"rounded-s": "shape",
	"rounded-e": "shape",
	"rounded-t": "shape",
	"rounded-r": "shape",
	"rounded-b": "shape",
	"rounded-l": "shape",
	"rounded-ss": "shape",
	"rounded-se": "shape",
	"rounded-ee": "shape",
	"rounded-es": "shape",
	"rounded-tl": "shape",
	"rounded-tr": "shape",
	"rounded-br": "shape",
	"rounded-bl": "shape",
	"border-w": "shape",
	"border-w-x": "shape",
	"border-w-y": "shape",
	"border-w-s": "shape",
	"border-w-e": "shape",
	"border-w-bs": "shape",
	"border-w-be": "shape",
	"border-w-t": "shape",
	"border-w-r": "shape",
	"border-w-b": "shape",
	"border-w-l": "shape",
	"divide-x": "shape",
	"divide-x-reverse": "shape",
	"divide-y": "shape",
	"divide-y-reverse": "shape",
	"border-style": "shape",
	"divide-style": "shape",
	"border-color": "color",
	"border-color-x": "color",
	"border-color-y": "color",
	"border-color-s": "color",
	"border-color-e": "color",
	"border-color-bs": "color",
	"border-color-be": "color",
	"border-color-t": "color",
	"border-color-r": "color",
	"border-color-b": "color",
	"border-color-l": "color",
	"divide-color": "color",
	"outline-style": "shape",
	"outline-offset": "shape",
	"outline-w": "shape",
	"outline-color": "color",
	shadow: "effects",
	"shadow-color": "color",
	"inset-shadow": "effects",
	"inset-shadow-color": "color",
	"ring-w": "shape",
	"ring-w-inset": "shape",
	"ring-color": "color",
	"ring-offset-w": "shape",
	"ring-offset-color": "color",
	"inset-ring-w": "shape",
	"inset-ring-color": "color",
	"text-shadow": "effects",
	"text-shadow-color": "color",
	opacity: "effects",
	"mix-blend": "effects",
	"bg-blend": "effects",
	"mask-clip": "effects",
	"mask-composite": "effects",
	"mask-image-linear-pos": "effects",
	"mask-image-linear-from-pos": "effects",
	"mask-image-linear-to-pos": "effects",
	"mask-image-linear-from-color": "color",
	"mask-image-linear-to-color": "color",
	"mask-image-t-from-pos": "effects",
	"mask-image-t-to-pos": "effects",
	"mask-image-t-from-color": "color",
	"mask-image-t-to-color": "color",
	"mask-image-r-from-pos": "effects",
	"mask-image-r-to-pos": "effects",
	"mask-image-r-from-color": "color",
	"mask-image-r-to-color": "color",
	"mask-image-b-from-pos": "effects",
	"mask-image-b-to-pos": "effects",
	"mask-image-b-from-color": "color",
	"mask-image-b-to-color": "color",
	"mask-image-l-from-pos": "effects",
	"mask-image-l-to-pos": "effects",
	"mask-image-l-from-color": "color",
	"mask-image-l-to-color": "color",
	"mask-image-x-from-pos": "effects",
	"mask-image-x-to-pos": "effects",
	"mask-image-x-from-color": "color",
	"mask-image-x-to-color": "color",
	"mask-image-y-from-pos": "effects",
	"mask-image-y-to-pos": "effects",
	"mask-image-y-from-color": "color",
	"mask-image-y-to-color": "color",
	"mask-image-radial": "effects",
	"mask-image-radial-from-pos": "effects",
	"mask-image-radial-to-pos": "effects",
	"mask-image-radial-from-color": "color",
	"mask-image-radial-to-color": "color",
	"mask-image-radial-shape": "effects",
	"mask-image-radial-size": "effects",
	"mask-image-radial-pos": "effects",
	"mask-image-conic-pos": "effects",
	"mask-image-conic-from-pos": "effects",
	"mask-image-conic-to-pos": "effects",
	"mask-image-conic-from-color": "color",
	"mask-image-conic-to-color": "color",
	"mask-mode": "effects",
	"mask-origin": "effects",
	"mask-position": "effects",
	"mask-repeat": "effects",
	"mask-size": "effects",
	"mask-type": "effects",
	"mask-image": "effects",
	filter: "effects",
	blur: "effects",
	brightness: "effects",
	contrast: "effects",
	"drop-shadow": "effects",
	"drop-shadow-color": "color",
	grayscale: "effects",
	"hue-rotate": "effects",
	invert: "effects",
	saturate: "effects",
	sepia: "effects",
	"backdrop-filter": "effects",
	"backdrop-blur": "effects",
	"backdrop-brightness": "effects",
	"backdrop-contrast": "effects",
	"backdrop-grayscale": "effects",
	"backdrop-hue-rotate": "effects",
	"backdrop-invert": "effects",
	"backdrop-opacity": "effects",
	"backdrop-saturate": "effects",
	"backdrop-sepia": "effects",
	"border-collapse": null,
	"border-spacing": "spacing",
	"border-spacing-x": "spacing",
	"border-spacing-y": "spacing",
	"table-layout": null,
	caption: null,
	transition: "motion",
	"transition-behavior": "motion",
	duration: "motion",
	ease: "motion",
	delay: "motion",
	animate: "motion",
	backface: null,
	perspective: null,
	"perspective-origin": null,
	rotate: null,
	"rotate-x": null,
	"rotate-y": null,
	"rotate-z": null,
	scale: null,
	"scale-x": null,
	"scale-y": null,
	"scale-z": null,
	"scale-3d": null,
	skew: null,
	"skew-x": null,
	"skew-y": null,
	transform: null,
	"transform-origin": null,
	"transform-style": null,
	translate: null,
	"translate-x": null,
	"translate-y": null,
	"translate-z": null,
	"translate-none": null,
	zoom: null,
	accent: "color",
	appearance: null,
	"caret-color": "color",
	"color-scheme": null,
	cursor: null,
	"field-sizing": null,
	"pointer-events": null,
	resize: null,
	"scroll-behavior": null,
	"scrollbar-thumb-color": "color",
	"scrollbar-track-color": "color",
	"scrollbar-gutter": null,
	"scrollbar-w": null,
	"scroll-m": null,
	"scroll-mx": null,
	"scroll-my": null,
	"scroll-ms": null,
	"scroll-me": null,
	"scroll-mbs": null,
	"scroll-mbe": null,
	"scroll-mt": null,
	"scroll-mr": null,
	"scroll-mb": null,
	"scroll-ml": null,
	"scroll-p": null,
	"scroll-px": null,
	"scroll-py": null,
	"scroll-ps": null,
	"scroll-pe": null,
	"scroll-pbs": null,
	"scroll-pbe": null,
	"scroll-pt": null,
	"scroll-pr": null,
	"scroll-pb": null,
	"scroll-pl": null,
	"snap-align": null,
	"snap-stop": null,
	"snap-type": null,
	"snap-strictness": null,
	touch: null,
	"touch-x": null,
	"touch-y": null,
	"touch-pz": null,
	select: null,
	"will-change": null,
	fill: "color",
	"stroke-w": "shape",
	stroke: "color",
	"forced-color-adjust": null
};
const ARBITRARY_PROPERTY_RULES = [
	[/(?:^|-)color$|^(?:background|fill|stroke|--tw-(?:gradient-(?:from|via|to)|shadow-color|ring-color|inset-ring-color|inset-shadow-color)|--tw-.*-color)$/, "color"],
	[/^(?:padding|gap$|row-gap$|column-gap$)/, "spacing"],
	[/^(?:font|letter-spacing$|line-height$|text-decoration|text-transform$|text-indent$|text-underline|word-spacing$|list-style)/, "typography"],
	[/^(?:border(?:-(?:top|right|bottom|left|inline|block)(?:-(?:start|end))?)?(?:-(?:width|style|radius))?$|border-.*-radius$|outline|--tw-ring-width$|--tw-ring-inset$)/, "shape"],
	[/^(?:box-shadow|text-shadow|opacity|filter|backdrop-filter|mix-blend-mode|background-blend-mode|--tw-(?:shadow|inset-shadow|drop-shadow|blur|brightness|contrast|grayscale|hue-rotate|invert|saturate|sepia|backdrop-.*)$)/, "effects"],
	[/^(?:transition|animation|--tw-(?:duration|ease|delay)$)/, "motion"]
];
const ARBITRARY_PREFIX = "arbitrary..";
const CATEGORIES = [
	"color",
	"typography",
	"spacing",
	"shape",
	"effects",
	"motion"
];
function categoryOf(groupId) {
	if (groupId === null) return null;
	if (groupId.startsWith(ARBITRARY_PREFIX)) {
		const property = groupId.slice(11);
		for (const [pattern, category] of ARBITRARY_PROPERTY_RULES) if (pattern.test(property)) return category;
		return null;
	}
	return GROUP_CATEGORY[groupId] ?? null;
}

//#endregion
//#region src/grammar/lengths.ts
const REM = 16;
function tokenize(input) {
	const tokens = [];
	const re = /\s*(?:(calc\(|\()|(\))|([+\-*/])|(\d*\.?\d+(?:e[+-]?\d+)?)(px|rem|em|%)?)/giy;
	let last = 0;
	let match;
	while (last < input.length) {
		re.lastIndex = last;
		match = re.exec(input);
		if (!match || match[0].length === 0) return /^\s*$/.test(input.slice(last)) ? tokens : null;
		last = re.lastIndex;
		if (match[1]) tokens.push({ kind: "(" });
		else if (match[2]) tokens.push({ kind: ")" });
		else if (match[3]) tokens.push({
			kind: "op",
			op: match[3]
		});
		else {
			const number = Number(match[4]);
			const unit = (match[5] ?? "").toLowerCase();
			if (unit === "%") return null;
			const value = unit === "px" ? { px: number } : unit === "rem" || unit === "em" ? { px: number * REM } : { n: number };
			tokens.push({
				kind: "num",
				value
			});
		}
	}
	return tokens;
}
function add(a, b, sign) {
	if ("px" in a && "px" in b) return { px: a.px + sign * b.px };
	if ("n" in a && "n" in b) return { n: a.n + sign * b.n };
	if ("n" in a && a.n === 0 && "px" in b) return { px: sign * b.px };
	if ("px" in a && "n" in b && b.n === 0) return a;
	return null;
}
function multiply(a, b) {
	if ("n" in a && "n" in b) return { n: a.n * b.n };
	if ("px" in a && "n" in b) return { px: a.px * b.n };
	if ("n" in a && "px" in b) return { px: a.n * b.px };
	return null;
}
function divide(a, b) {
	if (!("n" in b) || b.n === 0) return null;
	return "px" in a ? { px: a.px / b.n } : { n: a.n / b.n };
}
function evaluate(tokens) {
	let i = 0;
	const peek = () => tokens[i];
	const next = () => tokens[i++];
	const factor = () => {
		const token = next();
		if (!token) return null;
		if (token.kind === "num") return token.value;
		if (token.kind === "op" && token.op === "-") {
			const inner = factor();
			return inner && ("px" in inner ? { px: -inner.px } : { n: -inner.n });
		}
		if (token.kind === "op" && token.op === "+") return factor();
		if (token.kind === "(") {
			const inner = sum();
			return next()?.kind === ")" ? inner : null;
		}
		return null;
	};
	const product = () => {
		let left = factor();
		while (left) {
			const token = peek();
			if (token?.kind !== "op" || token.op !== "*" && token.op !== "/") break;
			next();
			const right = factor();
			if (!right) return null;
			left = token.op === "*" ? multiply(left, right) : divide(left, right);
		}
		return left;
	};
	const sum = () => {
		let left = product();
		while (left) {
			const token = peek();
			if (token?.kind !== "op" || token.op !== "+" && token.op !== "-") break;
			next();
			const right = product();
			if (!right) return null;
			left = add(left, right, token.op === "+" ? 1 : -1);
		}
		return left;
	};
	const result = sum();
	return i === tokens.length ? result : null;
}
function lengthInPx(value) {
	const tokens = tokenize(value.trim());
	if (!tokens || !tokens.length) return null;
	const result = evaluate(tokens);
	if (!result) return null;
	if ("px" in result) return result.px;
	return result.n === 0 ? 0 : null;
}
function formatPx(px) {
	return `${Number(px.toFixed(2))}px`;
}

//#endregion
//#region src/project/fs.ts
const TTL = 1e3;
const NODE_MODULES = /[\\/]node_modules[\\/]/;
const MAX_MEMO_ENTRIES = 5e4;
const memo = /* @__PURE__ */ new Map();
function memoize(key, compute, stale) {
	const hit = memo.get(key);
	const now = Date.now();
	if (hit && now - hit.at < 1e3 && !stale?.(hit.value)) return hit.value;
	const value = compute();
	if (memo.size >= MAX_MEMO_ENTRIES && !memo.has(key)) for (const oldest of memo.keys()) {
		memo.delete(oldest);
		if (memo.size <= MAX_MEMO_ENTRIES * .75) break;
	}
	memo.set(key, {
		at: now,
		value
	});
	return value;
}
const dirs = /* @__PURE__ */ new Map();
function dirOf(file) {
	let dir = dirs.get(file);
	if (dir === void 0) {
		if (dirs.size > 2e4) dirs.clear();
		dir = path.dirname(path.resolve(file));
		dirs.set(file, dir);
	}
	return dir;
}
function isDirectory(p) {
	return memoize(`dir:${p}`, () => {
		try {
			return fs.statSync(p).isDirectory();
		} catch {
			return false;
		}
	});
}
function isFile(p) {
	return memoize(`file:${p}`, () => {
		try {
			return fs.statSync(p).isFile();
		} catch {
			return false;
		}
	});
}
function mtimeOf(p) {
	return memoize(`mtime:${p}`, () => {
		try {
			return fs.statSync(p).mtimeMs;
		} catch {
			return null;
		}
	});
}
function realpath(p) {
	return memoize(`real:${p}`, () => {
		try {
			return fs.realpathSync.native(p);
		} catch {
			return p;
		}
	});
}
function findUp(fromDir, name) {
	const start = path.resolve(fromDir);
	return memoize(`up:${start}|${name}`, () => {
		let dir = start;
		for (let depth = 0; depth < 32; depth++) {
			const candidate = path.join(dir, name);
			if (memoize(`exists:${candidate}`, () => fs.existsSync(candidate))) return candidate;
			const parent = path.dirname(dir);
			if (parent === dir) break;
			dir = parent;
		}
		return null;
	});
}

//#endregion
//#region src/project/warn.ts
const seen = /* @__PURE__ */ new Set();
let sink = (message) => console.warn(message);
function warnOnce(key, message) {
	if (seen.has(key)) return;
	seen.add(key);
	sink(`[@shadcn/lint] ${message}`);
}

//#endregion
//#region src/grammar/validators.ts
var validators_exports = /* @__PURE__ */ __exportAll({
	isAny: () => isAny,
	isAnyNonArbitrary: () => isAnyNonArbitrary,
	isArbitraryFamilyName: () => isArbitraryFamilyName,
	isArbitraryImage: () => isArbitraryImage,
	isArbitraryLength: () => isArbitraryLength,
	isArbitraryNumber: () => isArbitraryNumber,
	isArbitraryPosition: () => isArbitraryPosition,
	isArbitraryShadow: () => isArbitraryShadow,
	isArbitrarySize: () => isArbitrarySize,
	isArbitraryValue: () => isArbitraryValue,
	isArbitraryVariable: () => isArbitraryVariable,
	isArbitraryVariableFamilyName: () => isArbitraryVariableFamilyName,
	isArbitraryVariableImage: () => isArbitraryVariableImage,
	isArbitraryVariableLength: () => isArbitraryVariableLength,
	isArbitraryVariablePosition: () => isArbitraryVariablePosition,
	isArbitraryVariableShadow: () => isArbitraryVariableShadow,
	isArbitraryVariableSize: () => isArbitraryVariableSize,
	isArbitraryVariableWeight: () => isArbitraryVariableWeight,
	isArbitraryWeight: () => isArbitraryWeight,
	isFraction: () => isFraction,
	isInteger: () => isInteger,
	isNamedContainerQuery: () => isNamedContainerQuery,
	isNumber: () => isNumber,
	isPercent: () => isPercent,
	isTshirtSize: () => isTshirtSize
});
const arbitraryValueRegex = /^\[(?:(\w[\w-]*):)?(.+)\]$/i;
const arbitraryVariableRegex = /^\((?:(\w[\w-]*):)?(.+)\)$/i;
const fractionRegex = /^\d+(?:\.\d+)?\/\d+(?:\.\d+)?$/;
const tshirtUnitRegex = /^(\d+(\.\d+)?)?(xs|sm|md|lg|xl)$/;
const lengthUnitRegex = /\d+(%|px|r?em|[sdl]?v([hwib]|min|max)|pt|pc|in|cm|mm|cap|ch|ex|r?lh|cq(w|h|i|b|min|max))|\b(calc|min|max|clamp)\(.+\)|^0$/;
const colorFunctionRegex = /^(rgba?|hsla?|hwb|(ok)?(lab|lch)|color-mix)\(.+\)$/;
const shadowRegex = /^(inset_)?-?((\d+)?\.?(\d+)[a-z]+|0)_-?((\d+)?\.?(\d+)[a-z]+|0)/;
const imageRegex = /^(url|image|image-set|cross-fade|element|(repeating-)?(linear|radial|conic)-gradient)\(.+\)$/;
const isFraction = (v) => fractionRegex.test(v);
const isNumber = (v) => !!v && !Number.isNaN(Number(v));
const isInteger = (v) => !!v && Number.isInteger(Number(v));
const isPercent = (v) => v.endsWith("%") && isNumber(v.slice(0, -1));
const isTshirtSize = (v) => tshirtUnitRegex.test(v);
const isAny = () => true;
const isLengthOnly = (v) => lengthUnitRegex.test(v) && !colorFunctionRegex.test(v);
const isNever = () => false;
const isShadow = (v) => shadowRegex.test(v);
const isImage = (v) => imageRegex.test(v);
const isAnyNonArbitrary = (v) => !isArbitraryValue(v) && !isArbitraryVariable(v);
const isNamedContainerQuery = (v) => v.startsWith("@container") && (v[10] === "/" && v[11] !== void 0 || v[11] === "s" && v[16] !== void 0 && v.startsWith("-size/", 10) || v[11] === "n" && v[18] !== void 0 && v.startsWith("-normal/", 10));
const getIsArbitraryValue = (value, testLabel, testValue) => {
	const result = arbitraryValueRegex.exec(value);
	if (result) {
		if (result[1]) return testLabel(result[1]);
		return testValue(result[2]);
	}
	return false;
};
const getIsArbitraryVariable = (value, testLabel, shouldMatchNoLabel = false) => {
	const result = arbitraryVariableRegex.exec(value);
	if (result) {
		if (result[1]) return testLabel(result[1]);
		return shouldMatchNoLabel;
	}
	return false;
};
const isLabelPosition = (l) => l === "position" || l === "percentage";
const isLabelImage = (l) => l === "image" || l === "url";
const isLabelSize = (l) => l === "length" || l === "size" || l === "bg-size";
const isLabelLength = (l) => l === "length";
const isLabelNumber = (l) => l === "number";
const isLabelFamilyName = (l) => l === "family-name";
const isLabelWeight = (l) => l === "number" || l === "weight";
const isLabelShadow = (l) => l === "shadow";
const isArbitrarySize = (v) => getIsArbitraryValue(v, isLabelSize, isNever);
const isArbitraryValue = (v) => arbitraryValueRegex.test(v);
const isArbitraryLength = (v) => getIsArbitraryValue(v, isLabelLength, isLengthOnly);
const isArbitraryNumber = (v) => getIsArbitraryValue(v, isLabelNumber, isNumber);
const isArbitraryWeight = (v) => getIsArbitraryValue(v, isLabelWeight, isAny);
const isArbitraryFamilyName = (v) => getIsArbitraryValue(v, isLabelFamilyName, isNever);
const isArbitraryPosition = (v) => getIsArbitraryValue(v, isLabelPosition, isNever);
const isArbitraryImage = (v) => getIsArbitraryValue(v, isLabelImage, isImage);
const isArbitraryShadow = (v) => getIsArbitraryValue(v, isLabelShadow, isShadow);
const isArbitraryVariable = (v) => arbitraryVariableRegex.test(v);
const isArbitraryVariableLength = (v) => getIsArbitraryVariable(v, isLabelLength);
const isArbitraryVariableFamilyName = (v) => getIsArbitraryVariable(v, isLabelFamilyName);
const isArbitraryVariablePosition = (v) => getIsArbitraryVariable(v, isLabelPosition);
const isArbitraryVariableSize = (v) => getIsArbitraryVariable(v, isLabelSize);
const isArbitraryVariableImage = (v) => getIsArbitraryVariable(v, isLabelImage);
const isArbitraryVariableShadow = (v) => getIsArbitraryVariable(v, isLabelShadow, true);
const isArbitraryVariableWeight = (v) => getIsArbitraryVariable(v, isLabelWeight, true);

//#endregion
//#region src/grammar/classifier.ts
const BUNDLED_CN = "0.3.2";
function cnVersionAt(resolvedConfigPath) {
	let dir = path.dirname(resolvedConfigPath);
	for (let i = 0; i < 6; i++) {
		const file = path.join(dir, "package.json");
		try {
			const pkg = JSON.parse(readFileSync(file, "utf8"));
			if (pkg.name === "cn" && pkg.version) return pkg.version;
		} catch {}
		const parent = path.dirname(dir);
		if (parent === dir) break;
		dir = parent;
	}
	return null;
}
function olderThan(version, than) {
	const parts = (v) => v.split(/[.-]/, 3).map((n) => Number(n) || 0);
	const [a, b] = [parts(version), parts(than)];
	for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] < b[i];
	return false;
}
const configCache = /* @__PURE__ */ new Map();
let bundledConfig = null;
function bundled() {
	bundledConfig ??= defaultConfig();
	return bundledConfig;
}
function resolveCnConfig(fromFile) {
	if (!fromFile) return bundled();
	const dir = dirOf(fromFile);
	const cached = configCache.get(dir);
	if (cached) return cached;
	let config;
	try {
		const require = createRequire(path.join(dir, "index.js"));
		const resolvedPath = require.resolve("cn/config");
		const byPath = configCache.get(resolvedPath);
		if (byPath) config = byPath;
		else {
			const version = cnVersionAt(resolvedPath);
			if (version && olderThan(version, "0.3.2")) {
				warnOnce(`cn-version:${resolvedPath}`, `This project's cn is ${version}. The linter's grammar needs cn ${BUNDLED_CN} or later, so it used its bundled cn ${BUNDLED_CN} instead. Update cn to lint with the grammar your app merges with.`);
				config = bundled();
			} else config = require(resolvedPath).defaultConfig();
			configCache.set(resolvedPath, config);
		}
	} catch {
		config = bundled();
	}
	configCache.set(dir, config);
	return config;
}
const validatorByName = validators_exports;
const ARBITRARY_PROPERTY_PREFIX = "arbitrary..";
function createNode() {
	return {
		next: /* @__PURE__ */ new Map(),
		validators: null,
		group: null
	};
}
function isMarker(def, key) {
	const keys = Object.keys(def);
	return keys.length === 1 && keys[0] === key && typeof def[key] === "string";
}
function getPart(node, path) {
	for (const part of path.split("-")) {
		let next = node.next.get(part);
		if (!next) {
			next = createNode();
			node.next.set(part, next);
		}
		node = next;
	}
	return node;
}
function buildTrie(config) {
	const root = createNode();
	const addValidator = (node, test, group) => {
		(node.validators ??= []).push({
			test,
			group
		});
	};
	const process = (def, node, group) => {
		if (typeof def === "string") {
			const target = def === "" ? node : getPart(node, def);
			target.group = group;
			return;
		}
		if (typeof def === "function") {
			if (def.isThemeGetter === true) {
				const getTheme = def;
				for (const inner of getTheme(config.theme)) process(inner, node, group);
				return;
			}
			addValidator(node, def, group);
			return;
		}
		if (isMarker(def, "$t")) {
			for (const inner of config.theme[def.$t] ?? []) process(inner, node, group);
			return;
		}
		if (isMarker(def, "$v")) {
			const name = def.$v;
			const test = validatorByName[name];
			if (!test) throw new Error(`cn-classifier: unknown validator "${name}"`);
			addValidator(node, test, group);
			return;
		}
		for (const [key, value] of Object.entries(def)) {
			const child = getPart(node, key);
			for (const inner of value) process(inner, child, group);
		}
	};
	for (const [group, defs] of Object.entries(config.classGroups)) for (const def of defs) process(def, root, group);
	return root;
}
function walk$1(parts, start, root) {
	const path = [root];
	let node = root;
	let index = start;
	while (index < parts.length) {
		const next = node.next.get(parts[index]);
		if (!next) break;
		node = next;
		path.push(node);
		index++;
	}
	let level = path.length - 1;
	if (index === parts.length) {
		if (node.group) return node.group;
		level--;
	}
	for (; level >= 0; level--) {
		const validators = path[level].validators;
		if (!validators) continue;
		const rest = parts.slice(start + level).join("-");
		for (const { test, group } of validators) if (test(rest)) return group;
	}
	return null;
}
function arbitraryPropertyGroup(base) {
	const content = base.slice(1, -1);
	const colon = content.indexOf(":");
	return colon > 0 ? ARBITRARY_PROPERTY_PREFIX + content.slice(0, colon) : null;
}
function postfixIndex(base) {
	let depth = 0;
	let index = -1;
	for (let i = 0; i < base.length; i++) {
		const char = base[i];
		if (char === "[" || char === "(") depth++;
		else if (char === "]" || char === ")") depth--;
		else if (char === "/" && depth === 0) index = i;
	}
	return index;
}
const RENAMED = /* @__PURE__ */ new Map([
	["flex-grow", "grow"],
	["flex-shrink", "shrink"],
	["overflow-ellipsis", "text-ellipsis"],
	["decoration-slice", "box-decoration-slice"],
	["decoration-clone", "box-decoration-clone"]
]);
const RENAMED_SCALE = /^flex-(grow|shrink)-(.+)$/;
function currentName(base) {
	const renamed = RENAMED.get(base);
	if (renamed) return renamed;
	const scale = RENAMED_SCALE.exec(base);
	return scale ? `${scale[1]}-${scale[2]}` : base;
}
function createClassifier(config = resolveCnConfig()) {
	const root = buildTrie(config);
	const postfixLookupGroups = new Set(config.postfixLookupClassGroups ?? []);
	const lookup = (base) => {
		if (base.startsWith("[") && base.endsWith("]")) return arbitraryPropertyGroup(base);
		const parts = base.split("-");
		return walk$1(parts, parts[0] === "" && parts.length > 1 ? 1 : 0, root);
	};
	const memo = /* @__PURE__ */ new Map();
	const groupOf = (token) => {
		const hit = memo.get(token);
		if (hit !== void 0) return hit;
		if (memo.size > 5e4) memo.clear();
		const group = classify(token);
		memo.set(token, group);
		return group;
	};
	const classify = (token) => {
		let base = splitVariants(token.trim()).base;
		if (base.endsWith("!")) base = base.slice(0, -1);
		else if (base.startsWith("!")) base = base.slice(1);
		if (!base) return null;
		base = currentName(base);
		const slash = postfixIndex(base);
		if (slash === -1) return lookup(base);
		const group = lookup(base.slice(0, slash));
		if (group && postfixLookupGroups.has(group)) return lookup(base) ?? group;
		return group ?? lookup(base);
	};
	return { groupOf };
}
const classifierByConfig = /* @__PURE__ */ new WeakMap();
function unknownGroups(config) {
	return Object.keys(config.classGroups).filter((group) => !(group in GROUP_CATEGORY));
}
function classifierFor(fromFile) {
	const config = resolveCnConfig(fromFile);
	let classifier = classifierByConfig.get(config);
	if (!classifier) {
		try {
			classifier = createClassifier(config);
		} catch (error) {
			warnOnce("classifier:fallback", `The installed cn's grammar could not be loaded (${error.message}); using the grammar bundled with @shadcn/lint. Update @shadcn/lint.`);
			const fallback = bundled();
			classifier = classifierByConfig.get(fallback) ?? createClassifier(fallback);
			classifierByConfig.set(fallback, classifier);
		}
		classifierByConfig.set(config, classifier);
		const unknown = unknownGroups(config);
		if (unknown.length) warnOnce(`groups:${unknown.join(",")}`, `The installed cn declares class groups this version of @shadcn/lint has no category for: ${unknown.join(", ")}. They are treated as layout. Update @shadcn/lint.`);
	}
	return classifier;
}

//#endregion
//#region src/grammar/colors.ts
const NAMED$1 = {
	aliceblue: "#f0f8ff",
	antiquewhite: "#faebd7",
	aqua: "#00ffff",
	aquamarine: "#7fffd4",
	azure: "#f0ffff",
	beige: "#f5f5dc",
	bisque: "#ffe4c4",
	black: "#000000",
	blanchedalmond: "#ffebcd",
	blue: "#0000ff",
	blueviolet: "#8a2be2",
	brown: "#a52a2a",
	burlywood: "#deb887",
	cadetblue: "#5f9ea0",
	chartreuse: "#7fff00",
	chocolate: "#d2691e",
	coral: "#ff7f50",
	cornflowerblue: "#6495ed",
	cornsilk: "#fff8dc",
	crimson: "#dc143c",
	cyan: "#00ffff",
	darkblue: "#00008b",
	darkcyan: "#008b8b",
	darkgoldenrod: "#b8860b",
	darkgray: "#a9a9a9",
	darkgreen: "#006400",
	darkgrey: "#a9a9a9",
	darkkhaki: "#bdb76b",
	darkmagenta: "#8b008b",
	darkolivegreen: "#556b2f",
	darkorange: "#ff8c00",
	darkorchid: "#9932cc",
	darkred: "#8b0000",
	darksalmon: "#e9967a",
	darkseagreen: "#8fbc8f",
	darkslateblue: "#483d8b",
	darkslategray: "#2f4f4f",
	darkslategrey: "#2f4f4f",
	darkturquoise: "#00ced1",
	darkviolet: "#9400d3",
	deeppink: "#ff1493",
	deepskyblue: "#00bfff",
	dimgray: "#696969",
	dimgrey: "#696969",
	dodgerblue: "#1e90ff",
	firebrick: "#b22222",
	floralwhite: "#fffaf0",
	forestgreen: "#228b22",
	fuchsia: "#ff00ff",
	gainsboro: "#dcdcdc",
	ghostwhite: "#f8f8ff",
	gold: "#ffd700",
	goldenrod: "#daa520",
	gray: "#808080",
	green: "#008000",
	greenyellow: "#adff2f",
	grey: "#808080",
	honeydew: "#f0fff0",
	hotpink: "#ff69b4",
	indianred: "#cd5c5c",
	indigo: "#4b0082",
	ivory: "#fffff0",
	khaki: "#f0e68c",
	lavender: "#e6e6fa",
	lavenderblush: "#fff0f5",
	lawngreen: "#7cfc00",
	lemonchiffon: "#fffacd",
	lightblue: "#add8e6",
	lightcoral: "#f08080",
	lightcyan: "#e0ffff",
	lightgoldenrodyellow: "#fafad2",
	lightgray: "#d3d3d3",
	lightgreen: "#90ee90",
	lightgrey: "#d3d3d3",
	lightpink: "#ffb6c1",
	lightsalmon: "#ffa07a",
	lightseagreen: "#20b2aa",
	lightskyblue: "#87cefa",
	lightslategray: "#778899",
	lightslategrey: "#778899",
	lightsteelblue: "#b0c4de",
	lightyellow: "#ffffe0",
	lime: "#00ff00",
	limegreen: "#32cd32",
	linen: "#faf0e6",
	magenta: "#ff00ff",
	maroon: "#800000",
	mediumaquamarine: "#66cdaa",
	mediumblue: "#0000cd",
	mediumorchid: "#ba55d3",
	mediumpurple: "#9370db",
	mediumseagreen: "#3cb371",
	mediumslateblue: "#7b68ee",
	mediumspringgreen: "#00fa9a",
	mediumturquoise: "#48d1cc",
	mediumvioletred: "#c71585",
	midnightblue: "#191970",
	mintcream: "#f5fffa",
	mistyrose: "#ffe4e1",
	moccasin: "#ffe4b5",
	navajowhite: "#ffdead",
	navy: "#000080",
	oldlace: "#fdf5e6",
	olive: "#808000",
	olivedrab: "#6b8e23",
	orange: "#ffa500",
	orangered: "#ff4500",
	orchid: "#da70d6",
	palegoldenrod: "#eee8aa",
	palegreen: "#98fb98",
	paleturquoise: "#afeeee",
	palevioletred: "#db7093",
	papayawhip: "#ffefd5",
	peachpuff: "#ffdab9",
	peru: "#cd853f",
	pink: "#ffc0cb",
	plum: "#dda0dd",
	powderblue: "#b0e0e6",
	purple: "#800080",
	rebeccapurple: "#663399",
	red: "#ff0000",
	rosybrown: "#bc8f8f",
	royalblue: "#4169e1",
	saddlebrown: "#8b4513",
	salmon: "#fa8072",
	sandybrown: "#f4a460",
	seagreen: "#2e8b57",
	seashell: "#fff5ee",
	sienna: "#a0522d",
	silver: "#c0c0c0",
	skyblue: "#87ceeb",
	slateblue: "#6a5acd",
	slategray: "#708090",
	slategrey: "#708090",
	snow: "#fffafa",
	springgreen: "#00ff7f",
	steelblue: "#4682b4",
	tan: "#d2b48c",
	teal: "#008080",
	thistle: "#d8bfd8",
	tomato: "#ff6347",
	turquoise: "#40e0d0",
	violet: "#ee82ee",
	wheat: "#f5deb3",
	white: "#ffffff",
	whitesmoke: "#f5f5f5",
	yellow: "#ffff00",
	yellowgreen: "#9acd32"
};
function linear(channel) {
	return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4;
}
function fromRgb(r, g, b) {
	const lr = linear(r);
	const lg = linear(g);
	const lb = linear(b);
	const l = Math.cbrt(.4122214708 * lr + .5363325363 * lg + .0514459929 * lb);
	const m = Math.cbrt(.2119034982 * lr + .6806995451 * lg + .1073969566 * lb);
	const s = Math.cbrt(.0883024619 * lr + .2817188376 * lg + .6299787005 * lb);
	return [
		.2104542553 * l + .793617785 * m - .0040720468 * s,
		1.9779984951 * l - 2.428592205 * m + .4505937099 * s,
		.0259040371 * l + .7827717662 * m - .808675766 * s
	];
}
function fromHwb(h, w, b) {
	if (w + b >= 1) {
		const gray = w / (w + b);
		return fromRgb(gray, gray, gray);
	}
	const [r, g, bl] = hslToRgb(h, 1, .5);
	const scale = (c) => c * (1 - w - b) + w;
	return fromRgb(scale(r), scale(g), scale(bl));
}
function hslToRgb(h, s, l) {
	const k = (n) => (n + h / 30) % 12;
	const a = s * Math.min(l, 1 - l);
	const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1));
	return [
		f(0),
		f(8),
		f(4)
	];
}
function fromHsl(h, s, l) {
	const k = (n) => (n + h / 30) % 12;
	const a = s * Math.min(l, 1 - l);
	const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1));
	return fromRgb(f(0), f(8), f(4));
}
function fromHex(hex) {
	let digits = hex.slice(1);
	if (digits.length === 3 || digits.length === 4) digits = [...digits].map((d) => d + d).join("");
	if (digits.length !== 6 && digits.length !== 8) return null;
	if (!/^[0-9a-f]+$/i.test(digits)) return null;
	const n = parseInt(digits.slice(0, 6), 16);
	return fromRgb((n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255);
}
function args(inner) {
	const [channels] = inner.split("/");
	return channels.trim().split(/[\s,]+/).filter(Boolean).slice(0, 3);
}
function channel(raw, scale, percentScale = 1) {
	if (raw === "none") return 0;
	if (raw.endsWith("%")) {
		const value = Number(raw.slice(0, -1));
		return Number.isFinite(value) ? value / 100 * percentScale : null;
	}
	const value = Number(raw.replace(/deg$/, ""));
	return Number.isFinite(value) ? value / scale : null;
}
function isNamedColor(value) {
	return Object.hasOwn(NAMED$1, value.trim().toLowerCase());
}
function parseColor(value) {
	const text = value.trim().toLowerCase();
	if (!text) return null;
	if (text.startsWith("#")) return fromHex(text);
	const named = NAMED$1[text];
	if (named) return fromHex(named);
	const match = text.match(/^([a-z]+)\((.*)\)$/s);
	if (!match) return null;
	const [, fn, inner] = match;
	const parts = args(inner);
	if (parts.length < 3) return null;
	switch (fn) {
		case "rgb":
		case "rgba": {
			const [r, g, b] = parts.map((p) => channel(p, 255));
			if (r === null || g === null || b === null) return null;
			return fromRgb(r, g, b);
		}
		case "hsl":
		case "hsla": {
			const h = channel(parts[0], 1);
			const s = channel(parts[1], 100);
			const l = channel(parts[2], 100);
			if (h === null || s === null || l === null) return null;
			return fromHsl(h, s, l);
		}
		case "hwb": {
			const h = channel(parts[0], 1);
			const w = channel(parts[1], 100);
			const b = channel(parts[2], 100);
			if (h === null || w === null || b === null) return null;
			return fromHwb(h, w, b);
		}
		case "oklch": {
			const l = channel(parts[0], 1);
			const c = channel(parts[1], 1, .4);
			const h = channel(parts[2], 1);
			if (l === null || c === null || h === null) return null;
			const rad = h * Math.PI / 180;
			return [
				l,
				c * Math.cos(rad),
				c * Math.sin(rad)
			];
		}
		case "oklab": {
			const l = channel(parts[0], 1);
			const a = channel(parts[1], 1, .4);
			const b = channel(parts[2], 1, .4);
			if (l === null || a === null || b === null) return null;
			return [
				l,
				a,
				b
			];
		}
		case "color": {
			if (parts[0] !== "srgb") return null;
			const [r, g, b] = args(inner.replace(/^\s*srgb\s+/, "")).map((p) => channel(p, 1));
			if (r == null || g == null || b == null) return null;
			return fromRgb(r, g, b);
		}
		default: return null;
	}
}
function colorDistance(a, b) {
	return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

//#endregion
//#region src/grammar/tailwind-theme.ts
const PALETTE = {
	"red-50": "oklch(97.1% 0.013 17.38)",
	"red-100": "oklch(93.6% 0.032 17.717)",
	"red-200": "oklch(88.5% 0.062 18.334)",
	"red-300": "oklch(80.8% 0.114 19.571)",
	"red-400": "oklch(70.4% 0.191 22.216)",
	"red-500": "oklch(63.7% 0.237 25.331)",
	"red-600": "oklch(57.7% 0.245 27.325)",
	"red-700": "oklch(50.5% 0.213 27.518)",
	"red-800": "oklch(44.4% 0.177 26.899)",
	"red-900": "oklch(39.6% 0.141 25.723)",
	"red-950": "oklch(25.8% 0.092 26.042)",
	"orange-50": "oklch(98% 0.016 73.684)",
	"orange-100": "oklch(95.4% 0.038 75.164)",
	"orange-200": "oklch(90.1% 0.076 70.697)",
	"orange-300": "oklch(83.7% 0.128 66.29)",
	"orange-400": "oklch(75% 0.183 55.934)",
	"orange-500": "oklch(70.5% 0.213 47.604)",
	"orange-600": "oklch(64.6% 0.222 41.116)",
	"orange-700": "oklch(55.3% 0.195 38.402)",
	"orange-800": "oklch(47% 0.157 37.304)",
	"orange-900": "oklch(40.8% 0.123 38.172)",
	"orange-950": "oklch(26.6% 0.079 36.259)",
	"amber-50": "oklch(98.7% 0.022 95.277)",
	"amber-100": "oklch(96.2% 0.059 95.617)",
	"amber-200": "oklch(92.4% 0.12 95.746)",
	"amber-300": "oklch(87.9% 0.169 91.605)",
	"amber-400": "oklch(82.8% 0.189 84.429)",
	"amber-500": "oklch(76.9% 0.188 70.08)",
	"amber-600": "oklch(66.6% 0.179 58.318)",
	"amber-700": "oklch(55.5% 0.163 48.998)",
	"amber-800": "oklch(47.3% 0.137 46.201)",
	"amber-900": "oklch(41.4% 0.112 45.904)",
	"amber-950": "oklch(27.9% 0.077 45.635)",
	"yellow-50": "oklch(98.7% 0.026 102.212)",
	"yellow-100": "oklch(97.3% 0.071 103.193)",
	"yellow-200": "oklch(94.5% 0.129 101.54)",
	"yellow-300": "oklch(90.5% 0.182 98.111)",
	"yellow-400": "oklch(85.2% 0.199 91.936)",
	"yellow-500": "oklch(79.5% 0.184 86.047)",
	"yellow-600": "oklch(68.1% 0.162 75.834)",
	"yellow-700": "oklch(55.4% 0.135 66.442)",
	"yellow-800": "oklch(47.6% 0.114 61.907)",
	"yellow-900": "oklch(42.1% 0.095 57.708)",
	"yellow-950": "oklch(28.6% 0.066 53.813)",
	"lime-50": "oklch(98.6% 0.031 120.757)",
	"lime-100": "oklch(96.7% 0.067 122.328)",
	"lime-200": "oklch(93.8% 0.127 124.321)",
	"lime-300": "oklch(89.7% 0.196 126.665)",
	"lime-400": "oklch(84.1% 0.238 128.85)",
	"lime-500": "oklch(76.8% 0.233 130.85)",
	"lime-600": "oklch(64.8% 0.2 131.684)",
	"lime-700": "oklch(53.2% 0.157 131.589)",
	"lime-800": "oklch(45.3% 0.124 130.933)",
	"lime-900": "oklch(40.5% 0.101 131.063)",
	"lime-950": "oklch(27.4% 0.072 132.109)",
	"green-50": "oklch(98.2% 0.018 155.826)",
	"green-100": "oklch(96.2% 0.044 156.743)",
	"green-200": "oklch(92.5% 0.084 155.995)",
	"green-300": "oklch(87.1% 0.15 154.449)",
	"green-400": "oklch(79.2% 0.209 151.711)",
	"green-500": "oklch(72.3% 0.219 149.579)",
	"green-600": "oklch(62.7% 0.194 149.214)",
	"green-700": "oklch(52.7% 0.154 150.069)",
	"green-800": "oklch(44.8% 0.119 151.328)",
	"green-900": "oklch(39.3% 0.095 152.535)",
	"green-950": "oklch(26.6% 0.065 152.934)",
	"emerald-50": "oklch(97.9% 0.021 166.113)",
	"emerald-100": "oklch(95% 0.052 163.051)",
	"emerald-200": "oklch(90.5% 0.093 164.15)",
	"emerald-300": "oklch(84.5% 0.143 164.978)",
	"emerald-400": "oklch(76.5% 0.177 163.223)",
	"emerald-500": "oklch(69.6% 0.17 162.48)",
	"emerald-600": "oklch(59.6% 0.145 163.225)",
	"emerald-700": "oklch(50.8% 0.118 165.612)",
	"emerald-800": "oklch(43.2% 0.095 166.913)",
	"emerald-900": "oklch(37.8% 0.077 168.94)",
	"emerald-950": "oklch(26.2% 0.051 172.552)",
	"teal-50": "oklch(98.4% 0.014 180.72)",
	"teal-100": "oklch(95.3% 0.051 180.801)",
	"teal-200": "oklch(91% 0.096 180.426)",
	"teal-300": "oklch(85.5% 0.138 181.071)",
	"teal-400": "oklch(77.7% 0.152 181.912)",
	"teal-500": "oklch(70.4% 0.14 182.503)",
	"teal-600": "oklch(60% 0.118 184.704)",
	"teal-700": "oklch(51.1% 0.096 186.391)",
	"teal-800": "oklch(43.7% 0.078 188.216)",
	"teal-900": "oklch(38.6% 0.063 188.416)",
	"teal-950": "oklch(27.7% 0.046 192.524)",
	"cyan-50": "oklch(98.4% 0.019 200.873)",
	"cyan-100": "oklch(95.6% 0.045 203.388)",
	"cyan-200": "oklch(91.7% 0.08 205.041)",
	"cyan-300": "oklch(86.5% 0.127 207.078)",
	"cyan-400": "oklch(78.9% 0.154 211.53)",
	"cyan-500": "oklch(71.5% 0.143 215.221)",
	"cyan-600": "oklch(60.9% 0.126 221.723)",
	"cyan-700": "oklch(52% 0.105 223.128)",
	"cyan-800": "oklch(45% 0.085 224.283)",
	"cyan-900": "oklch(39.8% 0.07 227.392)",
	"cyan-950": "oklch(30.2% 0.056 229.695)",
	"sky-50": "oklch(97.7% 0.013 236.62)",
	"sky-100": "oklch(95.1% 0.026 236.824)",
	"sky-200": "oklch(90.1% 0.058 230.902)",
	"sky-300": "oklch(82.8% 0.111 230.318)",
	"sky-400": "oklch(74.6% 0.16 232.661)",
	"sky-500": "oklch(68.5% 0.169 237.323)",
	"sky-600": "oklch(58.8% 0.158 241.966)",
	"sky-700": "oklch(50% 0.134 242.749)",
	"sky-800": "oklch(44.3% 0.11 240.79)",
	"sky-900": "oklch(39.1% 0.09 240.876)",
	"sky-950": "oklch(29.3% 0.066 243.157)",
	"blue-50": "oklch(97% 0.014 254.604)",
	"blue-100": "oklch(93.2% 0.032 255.585)",
	"blue-200": "oklch(88.2% 0.059 254.128)",
	"blue-300": "oklch(80.9% 0.105 251.813)",
	"blue-400": "oklch(70.7% 0.165 254.624)",
	"blue-500": "oklch(62.3% 0.214 259.815)",
	"blue-600": "oklch(54.6% 0.245 262.881)",
	"blue-700": "oklch(48.8% 0.243 264.376)",
	"blue-800": "oklch(42.4% 0.199 265.638)",
	"blue-900": "oklch(37.9% 0.146 265.522)",
	"blue-950": "oklch(28.2% 0.091 267.935)",
	"indigo-50": "oklch(96.2% 0.018 272.314)",
	"indigo-100": "oklch(93% 0.034 272.788)",
	"indigo-200": "oklch(87% 0.065 274.039)",
	"indigo-300": "oklch(78.5% 0.115 274.713)",
	"indigo-400": "oklch(67.3% 0.182 276.935)",
	"indigo-500": "oklch(58.5% 0.233 277.117)",
	"indigo-600": "oklch(51.1% 0.262 276.966)",
	"indigo-700": "oklch(45.7% 0.24 277.023)",
	"indigo-800": "oklch(39.8% 0.195 277.366)",
	"indigo-900": "oklch(35.9% 0.144 278.697)",
	"indigo-950": "oklch(25.7% 0.09 281.288)",
	"violet-50": "oklch(96.9% 0.016 293.756)",
	"violet-100": "oklch(94.3% 0.029 294.588)",
	"violet-200": "oklch(89.4% 0.057 293.283)",
	"violet-300": "oklch(81.1% 0.111 293.571)",
	"violet-400": "oklch(70.2% 0.183 293.541)",
	"violet-500": "oklch(60.6% 0.25 292.717)",
	"violet-600": "oklch(54.1% 0.281 293.009)",
	"violet-700": "oklch(49.1% 0.27 292.581)",
	"violet-800": "oklch(43.2% 0.232 292.759)",
	"violet-900": "oklch(38% 0.189 293.745)",
	"violet-950": "oklch(28.3% 0.141 291.089)",
	"purple-50": "oklch(97.7% 0.014 308.299)",
	"purple-100": "oklch(94.6% 0.033 307.174)",
	"purple-200": "oklch(90.2% 0.063 306.703)",
	"purple-300": "oklch(82.7% 0.119 306.383)",
	"purple-400": "oklch(71.4% 0.203 305.504)",
	"purple-500": "oklch(62.7% 0.265 303.9)",
	"purple-600": "oklch(55.8% 0.288 302.321)",
	"purple-700": "oklch(49.6% 0.265 301.924)",
	"purple-800": "oklch(43.8% 0.218 303.724)",
	"purple-900": "oklch(38.1% 0.176 304.987)",
	"purple-950": "oklch(29.1% 0.149 302.717)",
	"fuchsia-50": "oklch(97.7% 0.017 320.058)",
	"fuchsia-100": "oklch(95.2% 0.037 318.852)",
	"fuchsia-200": "oklch(90.3% 0.076 319.62)",
	"fuchsia-300": "oklch(83.3% 0.145 321.434)",
	"fuchsia-400": "oklch(74% 0.238 322.16)",
	"fuchsia-500": "oklch(66.7% 0.295 322.15)",
	"fuchsia-600": "oklch(59.1% 0.293 322.896)",
	"fuchsia-700": "oklch(51.8% 0.253 323.949)",
	"fuchsia-800": "oklch(45.2% 0.211 324.591)",
	"fuchsia-900": "oklch(40.1% 0.17 325.612)",
	"fuchsia-950": "oklch(29.3% 0.136 325.661)",
	"pink-50": "oklch(97.1% 0.014 343.198)",
	"pink-100": "oklch(94.8% 0.028 342.258)",
	"pink-200": "oklch(89.9% 0.061 343.231)",
	"pink-300": "oklch(82.3% 0.12 346.018)",
	"pink-400": "oklch(71.8% 0.202 349.761)",
	"pink-500": "oklch(65.6% 0.241 354.308)",
	"pink-600": "oklch(59.2% 0.249 0.584)",
	"pink-700": "oklch(52.5% 0.223 3.958)",
	"pink-800": "oklch(45.9% 0.187 3.815)",
	"pink-900": "oklch(40.8% 0.153 2.432)",
	"pink-950": "oklch(28.4% 0.109 3.907)",
	"rose-50": "oklch(96.9% 0.015 12.422)",
	"rose-100": "oklch(94.1% 0.03 12.58)",
	"rose-200": "oklch(89.2% 0.058 10.001)",
	"rose-300": "oklch(81% 0.117 11.638)",
	"rose-400": "oklch(71.2% 0.194 13.428)",
	"rose-500": "oklch(64.5% 0.246 16.439)",
	"rose-600": "oklch(58.6% 0.253 17.585)",
	"rose-700": "oklch(51.4% 0.222 16.935)",
	"rose-800": "oklch(45.5% 0.188 13.697)",
	"rose-900": "oklch(41% 0.159 10.272)",
	"rose-950": "oklch(27.1% 0.105 12.094)",
	"slate-50": "oklch(98.4% 0.003 247.858)",
	"slate-100": "oklch(96.8% 0.007 247.896)",
	"slate-200": "oklch(92.9% 0.013 255.508)",
	"slate-300": "oklch(86.9% 0.022 252.894)",
	"slate-400": "oklch(70.4% 0.04 256.788)",
	"slate-500": "oklch(55.4% 0.046 257.417)",
	"slate-600": "oklch(44.6% 0.043 257.281)",
	"slate-700": "oklch(37.2% 0.044 257.287)",
	"slate-800": "oklch(27.9% 0.041 260.031)",
	"slate-900": "oklch(20.8% 0.042 265.755)",
	"slate-950": "oklch(12.9% 0.042 264.695)",
	"gray-50": "oklch(98.5% 0.002 247.839)",
	"gray-100": "oklch(96.7% 0.003 264.542)",
	"gray-200": "oklch(92.8% 0.006 264.531)",
	"gray-300": "oklch(87.2% 0.01 258.338)",
	"gray-400": "oklch(70.7% 0.022 261.325)",
	"gray-500": "oklch(55.1% 0.027 264.364)",
	"gray-600": "oklch(44.6% 0.03 256.802)",
	"gray-700": "oklch(37.3% 0.034 259.733)",
	"gray-800": "oklch(27.8% 0.033 256.848)",
	"gray-900": "oklch(21% 0.034 264.665)",
	"gray-950": "oklch(13% 0.028 261.692)",
	"zinc-50": "oklch(98.5% 0 none)",
	"zinc-100": "oklch(96.7% 0.001 286.375)",
	"zinc-200": "oklch(92% 0.004 286.32)",
	"zinc-300": "oklch(87.1% 0.006 286.286)",
	"zinc-400": "oklch(70.5% 0.015 286.067)",
	"zinc-500": "oklch(55.2% 0.016 285.938)",
	"zinc-600": "oklch(44.2% 0.017 285.786)",
	"zinc-700": "oklch(37% 0.013 285.805)",
	"zinc-800": "oklch(27.4% 0.006 286.033)",
	"zinc-900": "oklch(21% 0.006 285.885)",
	"zinc-950": "oklch(14.1% 0.005 285.823)",
	"neutral-50": "oklch(98.5% 0 none)",
	"neutral-100": "oklch(97% 0 none)",
	"neutral-200": "oklch(92.2% 0 none)",
	"neutral-300": "oklch(87% 0 none)",
	"neutral-400": "oklch(70.8% 0 none)",
	"neutral-500": "oklch(55.6% 0 none)",
	"neutral-600": "oklch(43.9% 0 none)",
	"neutral-700": "oklch(37.1% 0 none)",
	"neutral-800": "oklch(26.9% 0 none)",
	"neutral-900": "oklch(20.5% 0 none)",
	"neutral-950": "oklch(14.5% 0 none)",
	"stone-50": "oklch(98.5% 0.001 106.423)",
	"stone-100": "oklch(97% 0.001 106.424)",
	"stone-200": "oklch(92.3% 0.003 48.717)",
	"stone-300": "oklch(86.9% 0.005 56.366)",
	"stone-400": "oklch(70.9% 0.01 56.259)",
	"stone-500": "oklch(55.3% 0.013 58.071)",
	"stone-600": "oklch(44.4% 0.011 73.639)",
	"stone-700": "oklch(37.4% 0.01 67.558)",
	"stone-800": "oklch(26.8% 0.007 34.298)",
	"stone-900": "oklch(21.6% 0.006 56.043)",
	"stone-950": "oklch(14.7% 0.004 49.25)",
	"mauve-50": "oklch(98.5% 0 none)",
	"mauve-100": "oklch(96% 0.003 325.6)",
	"mauve-200": "oklch(92.2% 0.005 325.62)",
	"mauve-300": "oklch(86.5% 0.012 325.68)",
	"mauve-400": "oklch(71.1% 0.019 323.02)",
	"mauve-500": "oklch(54.2% 0.034 322.5)",
	"mauve-600": "oklch(43.5% 0.029 321.78)",
	"mauve-700": "oklch(36.4% 0.029 323.89)",
	"mauve-800": "oklch(26.3% 0.024 320.12)",
	"mauve-900": "oklch(21.2% 0.019 322.12)",
	"mauve-950": "oklch(14.5% 0.008 326)",
	"olive-50": "oklch(98.8% 0.003 106.5)",
	"olive-100": "oklch(96.6% 0.005 106.5)",
	"olive-200": "oklch(93% 0.007 106.5)",
	"olive-300": "oklch(88% 0.011 106.6)",
	"olive-400": "oklch(73.7% 0.021 106.9)",
	"olive-500": "oklch(58% 0.031 107.3)",
	"olive-600": "oklch(46.6% 0.025 107.3)",
	"olive-700": "oklch(39.4% 0.023 107.4)",
	"olive-800": "oklch(28.6% 0.016 107.4)",
	"olive-900": "oklch(22.8% 0.013 107.4)",
	"olive-950": "oklch(15.3% 0.006 107.1)",
	"mist-50": "oklch(98.7% 0.002 197.1)",
	"mist-100": "oklch(96.3% 0.002 197.1)",
	"mist-200": "oklch(92.5% 0.005 214.3)",
	"mist-300": "oklch(87.2% 0.007 219.6)",
	"mist-400": "oklch(72.3% 0.014 214.4)",
	"mist-500": "oklch(56% 0.021 213.5)",
	"mist-600": "oklch(45% 0.017 213.2)",
	"mist-700": "oklch(37.8% 0.015 216)",
	"mist-800": "oklch(27.5% 0.011 216.9)",
	"mist-900": "oklch(21.8% 0.008 223.9)",
	"mist-950": "oklch(14.8% 0.004 228.8)",
	"taupe-50": "oklch(98.6% 0.002 67.8)",
	"taupe-100": "oklch(96% 0.002 17.2)",
	"taupe-200": "oklch(92.2% 0.005 34.3)",
	"taupe-300": "oklch(86.8% 0.007 39.5)",
	"taupe-400": "oklch(71.4% 0.014 41.2)",
	"taupe-500": "oklch(54.7% 0.021 43.1)",
	"taupe-600": "oklch(43.8% 0.017 39.3)",
	"taupe-700": "oklch(36.7% 0.016 35.7)",
	"taupe-800": "oklch(26.8% 0.011 36.5)",
	"taupe-900": "oklch(21.4% 0.009 43.1)",
	"taupe-950": "oklch(14.7% 0.004 49.3)",
	black: "#000",
	white: "#fff"
};
const FONT_SIZES = {
	xs: "0.75rem",
	sm: "0.875rem",
	base: "1rem",
	lg: "1.125rem",
	xl: "1.25rem",
	"2xl": "1.5rem",
	"3xl": "1.875rem",
	"4xl": "2.25rem",
	"5xl": "3rem",
	"6xl": "3.75rem",
	"7xl": "4.5rem",
	"8xl": "6rem",
	"9xl": "8rem",
	"shadow-2xs": "0px 1px 0px rgb(0 0 0 / 0.15)",
	"shadow-xs": "0px 1px 1px rgb(0 0 0 / 0.2)",
	"shadow-sm": "0px 1px 0px rgb(0 0 0 / 0.075), 0px 1px 1px rgb(0 0 0 / 0.075), 0px 2px 2px rgb(0 0 0 / 0.075)",
	"shadow-md": "0px 1px 1px rgb(0 0 0 / 0.1), 0px 1px 2px rgb(0 0 0 / 0.1), 0px 2px 4px rgb(0 0 0 / 0.1)",
	"shadow-lg": "0px 1px 2px rgb(0 0 0 / 0.1), 0px 3px 2px rgb(0 0 0 / 0.1), 0px 4px 8px rgb(0 0 0 / 0.1)"
};
const RADII = {
	xs: "0.125rem",
	sm: "0.25rem",
	md: "0.375rem",
	lg: "0.5rem",
	xl: "0.75rem",
	"2xl": "1rem",
	"3xl": "1.5rem",
	"4xl": "2rem"
};

//#endregion
//#region src/project/resolve.ts
const EXTENSIONS = [
	".tsx",
	".ts",
	".jsx",
	".js",
	".mjs",
	".cjs",
	".css",
	".svelte",
	".vue"
];
const SOURCE_FOR_JS = {
	".js": [".ts", ".tsx"],
	".jsx": [".tsx"],
	".mjs": [".mts", ".ts"],
	".cjs": [".cts", ".ts"]
};
function readJsonc(file) {
	let text;
	try {
		text = fs.readFileSync(file, "utf-8");
	} catch {
		return null;
	}
	let out = "";
	let i = 0;
	let quote = null;
	while (i < text.length) {
		const ch = text[i];
		const next = text[i + 1];
		if (quote) {
			out += ch;
			if (ch === "\\") {
				out += next ?? "";
				i += 2;
				continue;
			}
			if (ch === quote) quote = null;
			i++;
			continue;
		}
		if (ch === "\"" || ch === "'") {
			quote = ch;
			out += ch;
			i++;
			continue;
		}
		if (ch === "/" && next === "/") {
			while (i < text.length && text[i] !== "\n") i++;
			continue;
		}
		if (ch === "/" && next === "*") {
			i += 2;
			while (i < text.length && !(text[i] === "*" && text[i + 1] === "/")) i++;
			i += 2;
			continue;
		}
		out += ch;
		i++;
	}
	out = out.replace(/,(\s*[}\]])/g, "$1");
	try {
		return JSON.parse(out);
	} catch {
		return null;
	}
}
function packageRoot(fromFile) {
	const file = findUp(dirOf(fromFile), "package.json");
	return file ? path.dirname(file) : null;
}
function matchPattern(pattern, value) {
	const star = pattern.indexOf("*");
	if (star === -1) return pattern === value ? "" : null;
	const prefix = pattern.slice(0, star);
	const suffix = pattern.slice(star + 1);
	if (value.length < prefix.length + suffix.length || !value.startsWith(prefix) || !value.endsWith(suffix)) return null;
	return value.slice(prefix.length, value.length - suffix.length);
}
function expand(target, captured) {
	const star = target.indexOf("*");
	return star === -1 ? target : target.slice(0, star) + captured + target.slice(star + 1);
}
const tsconfigCache = /* @__PURE__ */ new Map();
function signatureOf$4(files) {
	return files.map((file) => `${file}:${mtimeOf(file) ?? "missing"}`).join("|");
}
function readTsconfigChain(file, visiting, files) {
	if (visiting.has(file) || visiting.size > 8) return [];
	visiting.add(file);
	files.push(file);
	const json = readJsonc(file);
	if (!json || typeof json !== "object") return [];
	const dir = path.dirname(file);
	const options = json.compilerOptions ?? {};
	const base = options.baseUrl ? path.resolve(dir, options.baseUrl) : dir;
	const own = Object.entries(options.paths ?? {}).map(([pattern, targets]) => ({
		pattern,
		targets: Array.isArray(targets) ? targets.map(String) : [],
		base
	}));
	const inherited = [].concat(json.extends ?? []).flatMap((parent) => {
		const resolved = resolveFile(String(parent), dir, dir, [".json"], { skipPaths: true });
		return resolved ? readTsconfigChain(resolved, visiting, files) : [];
	});
	return [...own, ...inherited];
}
function tsconfigPaths(rootDir) {
	const file = ["tsconfig.json", "jsconfig.json"].map((name) => path.join(rootDir, name)).find((candidate) => isFile(candidate));
	if (!file) return [];
	const cached = tsconfigCache.get(file);
	if (cached?.files.length && signatureOf$4(cached.files) === cached.signature) return cached.entries;
	tsconfigCache.set(file, {
		signature: "",
		files: [],
		entries: []
	});
	const files = [];
	const entries = readTsconfigChain(file, /* @__PURE__ */ new Set(), files);
	tsconfigCache.set(file, {
		signature: signatureOf$4(files),
		files,
		entries
	});
	return entries;
}
const packageJsonCache = /* @__PURE__ */ new Map();
function readPackageJson(dir) {
	const file = path.join(dir, "package.json");
	const mtimeMs = mtimeOf(file);
	if (mtimeMs === null) return null;
	const cached = packageJsonCache.get(file);
	if (cached && cached.mtimeMs === mtimeMs) return cached.json;
	const json = readJsonc(file);
	packageJsonCache.set(file, {
		mtimeMs,
		json
	});
	return json;
}
function pickTarget(value) {
	if (typeof value === "string") return value;
	if (Array.isArray(value)) {
		for (const item of value) {
			const picked = pickTarget(item);
			if (picked) return picked;
		}
		return null;
	}
	if (value && typeof value === "object") {
		for (const key of [
			"import",
			"default",
			"require",
			"node",
			"types"
		]) if (key in value) {
			const picked = pickTarget(value[key]);
			if (picked) return picked;
		}
		for (const key of Object.keys(value)) {
			if (key.startsWith(".")) continue;
			const picked = pickTarget(value[key]);
			if (picked) return picked;
		}
	}
	return null;
}
function mapSubpath(map, subpath) {
	const keys = Object.keys(map).filter((key) => key.startsWith(".") || key.startsWith("#")).sort((a, b) => b.length - a.length);
	const out = [];
	for (const key of keys) {
		const captured = matchPattern(key, subpath);
		if (captured === null) continue;
		const target = pickTarget(map[key]);
		if (target) out.push(key.includes("*") ? target.replaceAll("*", () => captured) : target);
	}
	return out;
}
function packageDirectory(name, fromDir) {
	const found = findUp(fromDir, path.join("node_modules", name));
	return found ? realpath(found) : null;
}
function selfPackageDirectory(name, fromDir) {
	const manifest = findUp(fromDir, "package.json");
	if (!manifest) return null;
	const dir = path.dirname(manifest);
	return readPackageJson(dir)?.name === name ? realpath(dir) : null;
}
function splitPackageSpecifier(spec) {
	const parts = spec.split("/");
	const nameLength = spec.startsWith("@") ? 2 : 1;
	if (parts.length < nameLength) return null;
	return {
		name: parts.slice(0, nameLength).join("/"),
		subpath: parts.slice(nameLength).join("/")
	};
}
function candidatesFor(spec, fromDir, rootDir, options = {}) {
	const out = [];
	if (spec.startsWith("./") || spec.startsWith("../") || spec === "." || spec === "..") {
		out.push(path.resolve(fromDir, spec));
		return out;
	}
	if (path.isAbsolute(spec)) {
		out.push(spec);
		return out;
	}
	if (!options.skipPaths) for (const entry of tsconfigPaths(rootDir)) {
		const captured = matchPattern(entry.pattern, spec);
		if (captured === null) continue;
		for (const target of entry.targets) out.push(path.resolve(entry.base, expand(target, captured)));
	}
	if (spec.startsWith("#")) {
		const imports = readPackageJson(rootDir)?.imports;
		if (imports && typeof imports === "object") for (const target of mapSubpath(imports, spec)) out.push(path.resolve(rootDir, target));
		return out;
	}
	const convention = spec.match(/^[@~]\/(.*)$/);
	if (convention) {
		out.push(path.join(rootDir, convention[1]));
		out.push(path.join(rootDir, "src", convention[1]));
		return out;
	}
	const kit = spec.match(/^\$lib(?:\/(.*))?$/);
	if (kit) {
		out.push(path.join(rootDir, "src/lib", kit[1] ?? ""));
		return out;
	}
	const pkg = splitPackageSpecifier(spec);
	if (!pkg) return out;
	const dir = selfPackageDirectory(pkg.name, rootDir) ?? selfPackageDirectory(pkg.name, fromDir) ?? packageDirectory(pkg.name, rootDir) ?? packageDirectory(pkg.name, fromDir);
	if (!dir) return out;
	const subpath = pkg.subpath ? `./${pkg.subpath}` : ".";
	const exportsMap = readPackageJson(dir)?.exports;
	if (exportsMap && typeof exportsMap === "object") {
		for (const target of mapSubpath(exportsMap, subpath)) out.push(path.resolve(dir, target));
		for (const target of mapSubpath(exportsMap, `${subpath}/*`)) out.push(path.dirname(path.resolve(dir, target)));
	}
	if (pkg.subpath) {
		out.push(path.join(dir, pkg.subpath));
		out.push(path.join(dir, "src", pkg.subpath));
	} else {
		out.push(dir);
		out.push(path.join(dir, "src"));
	}
	return out;
}
function resolveDirectory(spec, fromDir, rootDir) {
	return memoize(`resolve-dir:${fromDir}\u0000${rootDir}\u0000${spec}`, () => {
		for (const candidate of candidatesFor(spec, fromDir, rootDir)) if (isDirectory(candidate)) return realpath(candidate);
		return null;
	});
}
function resolveFileUncached(spec, fromDir, rootDir, extensions = EXTENSIONS, options = {}) {
	for (const candidate of candidatesFor(spec, fromDir, rootDir, options)) {
		if (isFile(candidate)) return realpath(candidate);
		const ext = path.extname(candidate);
		for (const source of SOURCE_FOR_JS[ext] ?? []) {
			const swapped = candidate.slice(0, -ext.length) + source;
			if (isFile(swapped)) return realpath(swapped);
		}
		for (const suffix of extensions) if (isFile(candidate + suffix)) return realpath(candidate + suffix);
		for (const suffix of extensions) {
			const index = path.join(candidate, `index${suffix}`);
			if (isFile(index)) return realpath(index);
		}
	}
	return null;
}
function resolveFile(spec, fromDir, rootDir, extensions = EXTENSIONS, options = {}) {
	const key = `resolve:${fromDir}|${rootDir}|${spec}|${extensions.join(",")}|${options.skipPaths ? 1 : 0}`;
	return memoize(key, () => resolveFileUncached(spec, fromDir, rootDir, extensions, options));
}

//#endregion
//#region src/project/components-json.ts
const cache$4 = /* @__PURE__ */ new Map();
function readProject(file) {
	const dir = path.dirname(file);
	const json = readJsonc(file);
	if (!json || typeof json !== "object") {
		warnOnce(`parse:${file}`, `${file} could not be parsed, so its aliases and theme are ignored and the project is read from package.json instead. Fix the JSON.`);
		return null;
	}
	const css = json.tailwind?.css;
	return {
		dir,
		file,
		root: packageRoot(file) ?? dir,
		aliases: readAliases(file, json.aliases),
		cssFile: typeof css === "string" && css ? path.resolve(dir, css) : null
	};
}
function readAliases(file, aliases) {
	if (aliases === void 0 || aliases === null || typeof aliases !== "object" || Array.isArray(aliases)) {
		if (aliases !== void 0 && aliases !== null) warnOnce(`aliases:${file}`, `The aliases in ${file} are not an object, so they are ignored and design-system components are looked for at the default alias. Make aliases an object like { "ui": "@/components/ui" }.`);
		return {};
	}
	const out = {};
	for (const [key, value] of Object.entries(aliases)) {
		if (typeof value === "string") {
			out[key] = value;
			continue;
		}
		if (key !== "ui" && key !== "components") continue;
		warnOnce(`aliases.${key}:${file}`, `aliases.${key} in ${file} is not a string, so it is ignored. Set it to an import path like "@/components${key === "ui" ? "/ui" : ""}".`);
	}
	return out;
}
function findProject(fromFile) {
	const dir = dirOf(fromFile);
	return memoize(`project:${dir}`, () => {
		const file = findUp(dir, "components.json");
		if (!file) return null;
		const mtimeMs = mtimeOf(file) ?? 0;
		const cached = cache$4.get(file);
		if (cached && cached.mtimeMs === mtimeMs) return cached.project;
		const project = readProject(file);
		cache$4.set(file, {
			mtimeMs,
			project
		});
		return project;
	});
}
function projectFor(fromFile) {
	const project = findProject(fromFile);
	if (project) return project;
	const root = packageRoot(fromFile);
	if (!root) return null;
	return {
		dir: root,
		file: null,
		root,
		aliases: {},
		cssFile: null
	};
}
function resolveAlias(project, alias) {
	const fromRoot = resolveDirectory(alias, project.dir, project.root);
	if (fromRoot || project.dir === project.root) return fromRoot;
	return resolveDirectory(alias, project.dir, project.dir);
}
function uiDirectory(project) {
	if (project.file) {
		const alias = project.aliases.ui ?? `${project.aliases.components ?? "@/components"}/ui`;
		const dir = resolveAlias(project, alias);
		if (dir) return dir;
		warnOnce(`ui:${project.file}`, `The ui alias "${alias}" in ${project.file} does not resolve to a directory, so design-system components are not recognized in this project. Fix aliases.ui, add the alias to tsconfig paths or package exports, or set componentImports.`);
		return null;
	}
	for (const candidate of ["components/ui", "src/components/ui"]) {
		const dir = path.join(project.dir, candidate);
		if (isDirectory(dir)) return dir;
	}
	return null;
}

//#endregion
//#region src/project/theme.ts
const cache$3 = /* @__PURE__ */ new Map();
function stripComments(css) {
	const parts = [];
	let start = 0;
	let i = 0;
	while (i < css.length) {
		const char = css[i];
		if (char === "/" && css[i + 1] === "*") {
			parts.push(css.slice(start, i));
			const end = css.indexOf("*/", i + 2);
			i = end === -1 ? css.length : end + 2;
			start = i;
		} else if (char === "\"" || char === "'") {
			i++;
			while (i < css.length && css[i] !== char) i += css[i] === "\\" ? 2 : 1;
			i++;
		} else if (css.startsWith("url(", i)) {
			const end = css.indexOf(")", i + 4);
			i = end === -1 ? css.length : end + 1;
		} else i++;
	}
	parts.push(css.slice(start));
	return parts.join("");
}
const COLOR_NAMESPACES = [
	"background-color",
	"text-color",
	"border-color",
	"divide-color",
	"ring-color",
	"outline-color",
	"accent-color",
	"caret-color",
	"placeholder-color",
	"text-decoration-color",
	"text-shadow-color",
	"drop-shadow-color",
	"fill",
	"stroke"
];
function applyTokenDeclarations(declarations, tokens, scoped) {
	for (const { name, value, theme } of declarations) {
		if (!theme) continue;
		const reset = value.trim() === "initial";
		if (name === "*") {
			if (reset) {
				tokens.clear();
				scoped?.clear();
			}
			continue;
		}
		const namespace = name.startsWith("color-") ? "color" : COLOR_NAMESPACES.find((candidate) => name.startsWith(`${candidate}-`));
		if (!namespace) continue;
		const token = name.slice(namespace.length + 1);
		let set = tokens;
		if (namespace !== "color") {
			if (!scoped) continue;
			set = scoped.get(namespace) ?? /* @__PURE__ */ new Set();
			scoped.set(namespace, set);
		}
		if (token === "*") {
			if (reset) set.clear();
		} else if (reset) set.delete(token);
		else set.add(token);
	}
}
const DARK_PRELUDE = /\.dark(?![\w-])|prefers-color-scheme\s*:\s*dark|data-(?:theme|mode)=["']?dark|@variant\s+dark\b/;
function parseDeclarations(css) {
	const values = /* @__PURE__ */ new Map();
	const themeNames = /* @__PURE__ */ new Set();
	const declarations = [];
	const stripped = stripComments(css);
	const stack = [];
	let start = 0;
	for (let i = 0; i < stripped.length; i++) {
		const char = stripped[i];
		if (char === "{") {
			const prelude = stripped.slice(start, i).trim();
			const outer = stack[stack.length - 1];
			stack.push({
				theme: (outer?.theme ?? false) || /^@theme\b/.test(prelude),
				dark: (outer?.dark ?? false) || DARK_PRELUDE.test(prelude)
			});
			start = i + 1;
		} else if (char === "}" || char === ";") {
			const match = stripped.slice(start, i).match(/^\s*--((?:[\w-]+\*?)|\*)\s*:\s*([\s\S]+?)\s*$/);
			const scope = stack[stack.length - 1];
			if (match && !scope?.dark) {
				values.set(match[1], match[2]);
				if (scope?.theme) themeNames.add(match[1]);
				declarations.push({
					name: match[1],
					value: match[2],
					theme: scope?.theme ?? false
				});
			}
			if (char === "}") stack.pop();
			start = i + 1;
		}
	}
	return {
		values,
		themeNames,
		declarations
	};
}
function resolveVariables(value, values, depth = 0) {
	if (!value.includes("var(")) return value;
	if (depth > 6) return null;
	let failed = false;
	const out = value.replace(/var\(\s*--([\w-]+)\s*(?:,\s*([^()]*(?:\([^()]*\)[^()]*)*))?\)/g, (_, name, fallback) => {
		const inner = values.get(name) ?? fallback;
		if (inner === void 0) {
			failed = true;
			return "";
		}
		const resolved = resolveVariables(inner.trim(), values, depth + 1);
		if (resolved === null) failed = true;
		return resolved ?? "";
	});
	return failed ? null : out;
}
function parseImports(css) {
	const out = [];
	for (const match of stripComments(css).matchAll(/@import\s+(?:url\(\s*)?["']([^"']+)["']\s*\)?[^;]*;/g)) out.push(match[1]);
	return out;
}
function parseUtilities(css) {
	const out = /* @__PURE__ */ new Set();
	for (const match of css.matchAll(/@utility\s+([\w-]+\*?)\s*\{/g)) out.add(match[1]);
	return out;
}
function parseClassSelectors(css) {
	const out = /* @__PURE__ */ new Set();
	const stripped = stripComments(css).replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'/g, "\"\"");
	for (const match of stripped.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)) out.add(match[1]);
	return out;
}
function isPackageFile(file) {
	return file.includes(`${path.sep}node_modules${path.sep}`);
}
function readTheme(cssFile, seen, read, fromPackage = false) {
	if (seen.has(cssFile) || seen.size > 64) return;
	seen.add(cssFile);
	read.files.push(cssFile);
	let css;
	try {
		css = fs.readFileSync(cssFile, "utf-8");
	} catch {
		return;
	}
	for (const name of parseUtilities(css)) read.utilities.add(name);
	for (const name of parseClassSelectors(css)) read.classes.add(name);
	const dir = path.dirname(cssFile);
	const root = packageRoot(cssFile) ?? dir;
	for (const spec of parseImports(css)) {
		if (spec === "tailwindcss" || spec.startsWith("tailwindcss/")) read.tailwind = true;
		const target = resolveFile(spec, dir, root, [".css"]);
		if (!target) {
			read.missingImports.push({
				spec,
				fromDir: dir,
				rootDir: root
			});
			continue;
		}
		readTheme(target, seen, read, fromPackage || isPackageFile(target));
	}
	if (!fromPackage) {
		const { values, themeNames, declarations } = parseDeclarations(css);
		applyTokenDeclarations(declarations, read.tokens, read.scoped);
		for (const [name, value] of values) read.values.set(name, value);
		for (const name of themeNames) read.themeNames.add(name);
		read.declarations.push(...declarations);
	}
}
function signatureOf$3(read) {
	return [...read.files.map((file) => `${file}:${mtimeOf(file) ?? "missing"}`), ...read.missingImports.map(({ spec, fromDir, rootDir }) => `${fromDir}:${spec}:${resolveFile(spec, fromDir, rootDir, [".css"]) ?? "missing"}`)].join("|");
}
function themeAt(cssFile) {
	const cached = cache$3.get(cssFile);
	const now = Date.now();
	if (cached && now - cached.checkedAt < 1e3) return cached.read;
	if (cached && signatureOf$3(cached.read) === cached.signature) {
		cached.checkedAt = now;
		return cached.read;
	}
	const read = {
		tokens: /* @__PURE__ */ new Set(),
		scoped: /* @__PURE__ */ new Map(),
		utilities: /* @__PURE__ */ new Set(),
		classes: /* @__PURE__ */ new Set(),
		values: /* @__PURE__ */ new Map(),
		themeNames: /* @__PURE__ */ new Set(),
		declarations: [],
		tailwind: false,
		files: [],
		missingImports: []
	};
	readTheme(cssFile, /* @__PURE__ */ new Set(), read);
	cache$3.set(cssFile, {
		signature: signatureOf$3(read),
		checkedAt: now,
		read
	});
	return read;
}
const SKIP_DIRS = /* @__PURE__ */ new Set([
	"node_modules",
	"dist",
	"build",
	"out",
	"coverage",
	"public",
	".next",
	".git",
	".turbo",
	".registry"
]);
function cssFilesUnder(dir, depth, out) {
	if (depth > 5 || out.length > 200) return;
	let entries;
	try {
		entries = fs.readdirSync(dir, { withFileTypes: true });
	} catch {
		return;
	}
	for (const entry of entries) {
		if (entry.name.startsWith(".") && entry.name !== ".") continue;
		const full = path.join(dir, entry.name);
		if (entry.isDirectory()) {
			if (!SKIP_DIRS.has(entry.name)) cssFilesUnder(full, depth + 1, out);
		} else if (entry.name.endsWith(".css")) out.push(full);
	}
}
const discovered = /* @__PURE__ */ new Map();
const DISCOVERY_TTL = 5e3;
function discoverThemeFile(root) {
	const cached = discovered.get(root);
	if (cached && Date.now() - cached.at < DISCOVERY_TTL && (cached.file === null || isFile(cached.file))) return cached.file;
	const files = [];
	cssFilesUnder(root, 0, files);
	let best = null;
	for (const file of files.sort()) {
		const read = themeAt(file);
		if (!read.tailwind) continue;
		const tokens = read.tokens.size;
		const depth = path.relative(root, file).split(path.sep).length;
		if (!best || tokens > best.tokens || tokens === best.tokens && depth < best.depth) best = {
			file,
			tokens,
			depth
		};
	}
	const file = best?.file ?? null;
	discovered.set(root, {
		at: Date.now(),
		file
	});
	return file;
}
function relativeTo(root, file) {
	return path.relative(root, file).replace(/\\/g, "/");
}
function themeFileFor(fromFile) {
	const project = projectFor(fromFile);
	if (!project) return null;
	if (project.cssFile) {
		if (isFile(project.cssFile)) return project.cssFile;
		const discovered = discoverThemeFile(project.root);
		warnOnce(`theme:missing:${project.cssFile}`, `components.json sets tailwind.css to ${relativeTo(project.root, project.cssFile)}, which does not exist. ${discovered ? `Using ${relativeTo(project.root, discovered)} until the path is fixed.` : "No stylesheet importing Tailwind was found under the project, so no-raw-colors cannot check declared tokens until the path is fixed."}`);
		return discovered;
	}
	return discoverThemeFile(project.root);
}
function tailwindEntryFor(fromFile) {
	const file = themeFileFor(fromFile);
	if (!file || themeAt(file).tailwind) return file;
	const project = projectFor(fromFile);
	if (!project) return file;
	const discovered = discoverThemeFile(project.root);
	warnOnce(`theme:no-tailwind:${file}`, `components.json sets tailwind.css to ${relativeTo(project.root, file)}, which does not import Tailwind. ${discovered ? `Using ${relativeTo(project.root, discovered)} to read the classes Tailwind knows until the path is fixed.` : "No stylesheet importing Tailwind was found under the project, so no-unknown-classes is using the grammar bundled with @shadcn/lint until the path is fixed."}`);
	return discovered;
}
function colorTokensFor(fromFile) {
	const cssFile = themeFileFor(fromFile);
	if (!cssFile) return null;
	const { tokens } = themeAt(cssFile);
	return tokens.size ? tokens : null;
}
function scopedColorTokensFor(fromFile) {
	const cssFile = themeFileFor(fromFile);
	if (!cssFile) return null;
	return themeAt(cssFile).scoped;
}
function colorsOf(read) {
	if (read.colors) return read.colors;
	const colors = /* @__PURE__ */ new Map();
	for (const token of read.tokens) {
		const raw = read.values.get(`color-${token}`);
		if (!raw) continue;
		const resolved = resolveVariables(raw, read.values);
		const lab = resolved ? parseColor(resolved) : null;
		if (lab) colors.set(token, lab);
	}
	read.colors = colors;
	return colors;
}
const SCALE_DEFAULTS = {
	radius: RADII,
	text: FONT_SIZES
};
function scaleOf(read, kind) {
	read.scales ??= {
		radius: buildScale(read, "radius"),
		text: buildScale(read, "text")
	};
	return read.scales[kind];
}
function defaultScale(kind) {
	const scale = /* @__PURE__ */ new Map();
	for (const [name, value] of Object.entries(SCALE_DEFAULTS[kind])) {
		const px = lengthInPx(value);
		if (px !== null) scale.set(name, px);
	}
	return scale;
}
function buildScale(read, kind) {
	const scale = defaultScale(kind);
	const prefix = `${kind}-`;
	for (const { name, value, theme } of read.declarations) {
		if (!theme) continue;
		const reset = value.trim() === "initial";
		if (name === "*") {
			if (reset) scale.clear();
			continue;
		}
		if (!name.startsWith(prefix) || name.includes("--")) continue;
		const step = name.slice(prefix.length);
		if (step === "*") {
			if (reset) scale.clear();
			continue;
		}
		if (reset) {
			scale.delete(step);
			continue;
		}
		const resolved = resolveVariables(value, read.values);
		const px = resolved ? lengthInPx(resolved) : null;
		if (px !== null) scale.set(step, px);
		else scale.delete(step);
	}
	return scale;
}
const DEFAULT_SCALES = {
	radius: defaultScale("radius"),
	text: defaultScale("text")
};
function colorValuesFor(fromFile) {
	const cssFile = themeFileFor(fromFile);
	if (!cssFile) return null;
	const read = themeAt(cssFile);
	return read.tokens.size ? colorsOf(read) : null;
}
function spacingBaseFor(fromFile) {
	const cssFile = themeFileFor(fromFile);
	if (!cssFile) return 4;
	const read = themeAt(cssFile);
	if (read.spacing !== void 0) return read.spacing;
	let raw = "0.25rem";
	for (const { name, value, theme } of read.declarations) {
		if (!theme) continue;
		if (name === "*" && value.trim() === "initial") raw = null;
		else if (name === "spacing") raw = value.trim() === "initial" ? null : value;
	}
	const resolved = raw === null ? null : resolveVariables(raw, read.values);
	const px = resolved ? lengthInPx(resolved) : null;
	return read.spacing = px && px > 0 ? px : null;
}
function scaleFor(fromFile, kind) {
	const cssFile = themeFileFor(fromFile);
	if (!cssFile) return DEFAULT_SCALES[kind];
	return scaleOf(themeAt(cssFile), kind);
}
function themeVocabularyFor(fromFile) {
	const cssFile = themeFileFor(fromFile);
	if (!cssFile) return null;
	const read = themeAt(cssFile);
	return read.vocabulary ??= {
		names: read.themeNames,
		tokens: read.tokens,
		utilities: read.utilities
	};
}
const utilityPrefixes = /* @__PURE__ */ new WeakMap();
function utilityPrefixesOf(utilities) {
	let list = utilityPrefixes.get(utilities);
	if (!list) {
		list = [...utilities].filter((name) => name.endsWith("*")).map((name) => name.slice(0, -1));
		utilityPrefixes.set(utilities, list);
	}
	return list;
}
function declaresUtility(fromFile, token) {
	const base = normalizeClass(token).replace(OPACITY_MODIFIER, "");
	if (!base) return false;
	const { utilities } = knownClassesFor(fromFile);
	if (utilities.has(base)) return true;
	return utilityPrefixesOf(utilities).some((prefix) => base.startsWith(prefix));
}
function declaresClass(fromFile, token) {
	if (declaresUtility(fromFile, token)) return true;
	const base = normalizeClass(token).replace(OPACITY_MODIFIER, "");
	return !!base && knownClassesFor(fromFile).classes.has(base);
}
function knownClassesFor(fromFile) {
	const cssFile = themeFileFor(fromFile);
	if (!cssFile) return {
		utilities: /* @__PURE__ */ new Set(),
		classes: /* @__PURE__ */ new Set()
	};
	const { utilities, classes } = themeAt(cssFile);
	return {
		utilities,
		classes
	};
}

//#endregion
//#region src/project/namespaces.ts
const NAMESPACES = [
	{
		prefix: "text-shadow-",
		namespace: "text-shadow-",
		group: "text-shadow",
		overColor: true
	},
	{
		prefix: "inset-shadow-",
		namespace: "inset-shadow-",
		group: "inset-shadow",
		overColor: true
	},
	{
		prefix: "drop-shadow-",
		namespace: "drop-shadow-",
		group: "drop-shadow",
		overColor: true
	},
	{
		prefix: "shadow-",
		namespace: "shadow-",
		group: "shadow",
		overColor: true
	},
	{
		prefix: "text-",
		namespace: "text-",
		group: "font-size",
		overColor: false
	},
	{
		prefix: "bg-",
		namespace: "background-image-",
		group: "bg-image",
		overColor: false
	}
];
const ANIMATE_PREFIX = "animate-";
const memos$1 = /* @__PURE__ */ new WeakMap();
function memoFor(vocabulary) {
	let memo = memos$1.get(vocabulary);
	if (!memo) {
		memo = /* @__PURE__ */ new Map();
		memos$1.set(vocabulary, memo);
	}
	if (memo.size > 5e4) memo.clear();
	return memo;
}
function valueOf$1(base, prefix) {
	const rest = base.slice(prefix.length);
	const modifier = rest.match(OPACITY_MODIFIER)?.[0] ?? "";
	const value = rest.slice(0, rest.length - modifier.length);
	if (!value || value.startsWith("[") || value.startsWith("(")) return null;
	return value;
}
function lookup$1(vocabulary, token) {
	const base = normalizeClass(token);
	const entry = NAMESPACES.find((n) => base.startsWith(n.prefix));
	if (!entry) return null;
	const value = valueOf$1(base, entry.prefix);
	if (!value) return null;
	if (!entry.overColor && vocabulary.tokens.has(value)) return null;
	return vocabulary.names.has(`${entry.namespace}${value}`) ? entry.group : null;
}
function themeGroupFor(fromFile, token) {
	if (!fromFile) return null;
	const vocabulary = themeVocabularyFor(fromFile);
	if (!vocabulary) return null;
	const memo = memoFor(vocabulary);
	let group = memo.get(token);
	if (group === void 0) {
		group = lookup$1(vocabulary, token);
		memo.set(token, group);
	}
	return group;
}
function animationGroupFor(fromFile, token) {
	if (!fromFile) return null;
	const base = normalizeClass(token);
	if (!base.startsWith(ANIMATE_PREFIX)) return null;
	if (!valueOf$1(base, ANIMATE_PREFIX)) return null;
	if (themeVocabularyFor(fromFile)?.names.has(base)) return "animate";
	return declaresClass(fromFile, token) ? "animate" : null;
}
function projectClassifierFor(fromFile) {
	const { groupOf: grammarGroupOf } = classifierFor(fromFile);
	const groupOf = (token) => {
		const group = grammarGroupOf(token);
		if (!group) return animationGroupFor(fromFile, token);
		if (categoryOf(group) !== "color") return group;
		return themeGroupFor(fromFile, token) ?? group;
	};
	return { groupOf };
}

//#endregion
//#region src/project/parser.ts
const require = createRequire(import.meta.url);
function langOf(file) {
	switch (path.extname(file).toLowerCase()) {
		case ".tsx": return "tsx";
		case ".ts":
		case ".mts":
		case ".cts": return "ts";
		case ".jsx": return "jsx";
		default: return "js";
	}
}
const SFC_RE = /\.(svelte|vue)$/i;
const SCRIPT_RE = /<script(?=[\t\n\f\r />])[^>]*>([\s\S]*?)<\/script(?=[\t\n\f\r />])[^>]*>/gi;
function isSfc(file) {
	return SFC_RE.test(file);
}
function sfcNameOf(file) {
	return path.basename(file, path.extname(file)).split(/[^A-Za-z0-9]+/).filter(Boolean).map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join("");
}
const STYLE_RE = /<style\b[^>]*>([\s\S]*?)<\/style\s*>/gi;
function styleClassesOf(source) {
	const out = /* @__PURE__ */ new Set();
	for (const match of source.matchAll(STYLE_RE)) for (const name of parseClassSelectors(match[1])) out.add(name);
	return out;
}
function scriptOf(source) {
	let out = "";
	let last = 0;
	const blank = (text) => text.replace(/[^\n\r]/g, " ");
	for (const match of source.matchAll(SCRIPT_RE)) {
		const start = match.index + match[0].indexOf(">") + 1;
		const end = start + match[1].length;
		out += blank(source.slice(last, start)) + source.slice(start, end);
		last = end;
	}
	return out + blank(source.slice(last));
}
function loadOxc() {
	try {
		const oxc = require("oxc-parser");
		return {
			kind: "oxc",
			parse(source, file) {
				const result = oxc.parseSync(path.basename(file), source, {
					lang: langOf(file),
					sourceType: "module"
				});
				if (!result.program?.body?.length && result.errors.some((e) => e.severity === "Error")) throw new Error("oxc-parser: unparsable");
				return result.program;
			}
		};
	} catch {
		return null;
	}
}
function createParser() {
	const oxc = loadOxc();
	if (!oxc) throw new Error("oxc-parser is not installed");
	return oxc;
}
let active = null;
function parseSource(source, file) {
	active ??= createParser();
	return isSfc(file) ? active.parse(scriptOf(source), `${file}.ts`) : active.parse(source, file);
}

//#endregion
//#region src/project/component-imports.ts
function importNameOf(imported, root, property) {
	const suffix = property !== null && !imported.namespace ? property : "";
	return {
		source: imported.source,
		exportName: imported.namespace ? property ?? "" : imported.original,
		name: imported.namespace ? property ?? "" : `${imported.original === "default" ? root : imported.original}${suffix}`,
		suffix
	};
}
function componentFromImport(index, binding, importedName, patterns) {
	if (binding && index.owns(binding.file)) {
		const component = `${binding.name}${importedName.suffix}`;
		const indexed = index.files.get(component);
		if (!NODE_MODULES.test(binding.file) || indexed) {
			const file = indexed ?? binding.file;
			return {
				component,
				file: NODE_MODULES.test(file) ? null : file
			};
		}
	}
	if (patterns.some((pattern) => pattern.test(importedName.source))) return {
		component: binding && isSfc(binding.file) ? `${binding.name}${importedName.suffix}` : importedName.name,
		file: binding?.file ?? null
	};
	return null;
}

//#endregion
//#region src/project/modules.ts
const parsed = /* @__PURE__ */ new Map();
const DECLARATION_RE = /export\s+(?:default\s+)?(?:async\s+)?(?:function\*?|const|let|var|class|enum)\s+([A-Za-z_$][\w$]*)/g;
const DEFAULT_DECLARATION_RE = /export\s+default\s+(?:async\s+)?(?:function\*?|class)\s+([A-Za-z_$][\w$]*)/;
const DEFAULT_IDENTIFIER_RE = /export\s+default\s+([A-Za-z_$][\w$]*)\s*;?\s*$/m;
const DEFAULT_WRAPPED_RE = /export\s+default\s+(?:React\.)?(?:memo|forwardRef)\(\s*(?:function\s+)?([A-Za-z_$][\w$]*)/;
const NAMED_RE = /export\s*(type\s+)?\{([^}]*)\}\s*(?:from\s*["']([^"']+)["'])?/g;
const STAR_RE = /export\s*\*\s*(?:as\s+([\w$]+)\s+)?from\s*["']([^"']+)["']/g;
const IMPORT_RE = /import\s+(?!type\s)(?:([\w$]+)\s*,?\s*)?(?:\*\s*as\s+([\w$]+)|\{([^}]*)\})?\s*from\s*["']([^"']+)["']/g;
const COMMENT_RE = /\/\*[\s\S]*?\*\/|\/\/[^\n\r]*/g;
function parseNamed(list) {
	const out = [];
	for (const raw of list.replace(COMMENT_RE, "").split(",")) {
		const item = raw.trim();
		if (!item || item.startsWith("type ")) continue;
		const [local, exported] = item.split(/\s+as\s+/).map((s) => s.trim());
		if (!local) continue;
		out.push({
			exported: exported ?? local,
			local
		});
	}
	return out;
}
function parseModule(file) {
	const module = {
		local: /* @__PURE__ */ new Set(),
		imports: /* @__PURE__ */ new Map(),
		defaultName: null,
		sfc: isSfc(file),
		named: [],
		namedIndices: /* @__PURE__ */ new Map(),
		stars: []
	};
	let source;
	try {
		source = fs.readFileSync(file, "utf-8");
	} catch {
		return module;
	}
	if (module.sfc) source = scriptOf(source);
	for (const match of source.matchAll(IMPORT_RE)) {
		const [, defaultLocal, namespaceLocal, list, spec] = match;
		if (defaultLocal) module.imports.set(defaultLocal, {
			spec,
			name: "default"
		});
		if (namespaceLocal) module.imports.set(namespaceLocal, {
			spec,
			name: "*"
		});
		for (const { exported, local } of list ? parseNamed(list) : []) module.imports.set(exported, {
			spec,
			name: local
		});
	}
	for (const match of source.matchAll(DECLARATION_RE)) module.local.add(match[1]);
	const defaultDeclaration = source.match(DEFAULT_DECLARATION_RE);
	const defaultIdentifier = source.match(DEFAULT_IDENTIFIER_RE) ?? source.match(DEFAULT_WRAPPED_RE);
	if (defaultDeclaration) module.defaultName = defaultDeclaration[1];
	else if (defaultIdentifier) {
		module.defaultName = defaultIdentifier[1];
		module.local.add(defaultIdentifier[1]);
	}
	if (module.sfc) module.defaultName = sfcNameOf(file);
	for (const match of source.matchAll(NAMED_RE)) {
		if (match[1]) continue;
		const spec = match[3] ?? "";
		for (const { exported, local } of parseNamed(match[2])) module.named.push({
			exported,
			local,
			spec
		});
	}
	for (const match of source.matchAll(STAR_RE)) {
		if (match[1]) continue;
		module.stars.push(match[2]);
	}
	for (let index = 0; index < module.named.length; index++) {
		const name = module.named[index].exported;
		const indices = module.namedIndices.get(name);
		if (indices) indices.push(index);
		else module.namedIndices.set(name, [index]);
	}
	return module;
}
function moduleOf(file) {
	const mtimeMs = mtimeOf(file);
	if (mtimeMs === null) return null;
	const cached = parsed.get(file);
	if (cached && cached.mtimeMs === mtimeMs) return cached.module;
	const module = parseModule(file);
	parsed.set(file, {
		mtimeMs,
		module
	});
	return module;
}
function resolveFrom(file, spec) {
	const dir = path.dirname(file);
	return resolveFile(spec, dir, packageRoot(file) ?? dir);
}
function signatureOf$2(dependencies) {
	let signature = "";
	for (const dependency of dependencies) signature += `${dependency}:${mtimeOf(dependency) ?? "missing"}|`;
	return signature;
}
function derive(key, compute) {
	return memoize(key, () => {
		const dependencies = /* @__PURE__ */ new Set();
		return {
			value: compute(dependencies),
			dependencies,
			signature: signatureOf$2(dependencies)
		};
	}, (hit) => hit.signature !== signatureOf$2(hit.dependencies));
}
function exportsOf(file, visiting = /* @__PURE__ */ new Set(), deps) {
	if (visiting.size) return collectExports(file, visiting, deps);
	const cached = derive(`exports:${file}`, (dependencies) => collectExports(file, /* @__PURE__ */ new Set(), dependencies));
	if (deps) for (const dependency of cached.dependencies) deps.add(dependency);
	return cached.value;
}
function collectExports(file, visiting, deps) {
	const exports = /* @__PURE__ */ new Map();
	if (visiting.has(file)) return exports;
	deps?.add(file);
	const module = moduleOf(file);
	if (!module) return exports;
	visiting.add(file);
	for (const name of module.local) exports.set(name, {
		file,
		name
	});
	if (module.sfc && module.defaultName) exports.set("default", {
		file,
		name: module.defaultName
	});
	else if (module.defaultName) {
		const imported = module.imports.get(module.defaultName);
		const target = imported && imported.name !== "*" ? resolveFrom(file, imported.spec) : null;
		const inner = target ? exportsOf(target, visiting, deps) : null;
		exports.set("default", inner?.get(imported.name) ?? (target ? {
			file: target,
			name: imported.name
		} : {
			file,
			name: module.defaultName
		}));
	}
	for (const { exported, local, spec } of module.named) {
		if (!spec) {
			const imported = module.imports.get(local);
			if (imported && imported.name !== "*") {
				const target = resolveFrom(file, imported.spec);
				const inner = target ? exportsOf(target, visiting, deps) : null;
				exports.set(exported, inner?.get(imported.name) ?? (target ? {
					file: target,
					name: imported.name
				} : {
					file,
					name: local
				}));
				continue;
			}
			exports.set(exported, exports.get(local) ?? {
				file,
				name: local
			});
			continue;
		}
		const target = resolveFrom(file, spec);
		if (!target) continue;
		const inner = exportsOf(target, visiting, deps);
		exports.set(exported, inner.get(local) ?? {
			file: target,
			name: local
		});
	}
	for (const spec of module.stars) {
		const target = resolveFrom(file, spec);
		if (!target) continue;
		for (const [name, binding] of exportsOf(target, visiting, deps)) if (name !== "default" && !exports.has(name)) exports.set(name, binding);
	}
	visiting.delete(file);
	return exports;
}
function exportRoute(module, file, name) {
	const importedRoute = (local) => {
		const imported = module.imports.get(local);
		const target = imported && imported.name !== "*" ? resolveFrom(file, imported.spec) : null;
		return target ? {
			binding: {
				file: target,
				name: imported.name
			},
			follow: true
		} : {
			binding: {
				file,
				name: local
			},
			follow: false
		};
	};
	let before = module.named.length;
	let fallback = null;
	for (;;) {
		const indices = module.namedIndices.get(name) ?? [];
		let aliased = false;
		for (let i = indices.length - 1; i >= 0; i--) {
			const index = indices[i];
			if (index >= before) continue;
			const { local, spec } = module.named[index];
			if (!spec) {
				const imported = module.imports.get(local);
				if (imported && imported.name !== "*") return importedRoute(local);
				name = local;
				before = index;
				fallback = {
					file,
					name
				};
				aliased = true;
				break;
			}
			const target = resolveFrom(file, spec);
			if (target) return {
				binding: {
					file: target,
					name: local
				},
				follow: true
			};
		}
		if (aliased) continue;
		if (name === "default" && module.defaultName) return module.sfc ? {
			binding: {
				file,
				name: module.defaultName
			},
			follow: false
		} : importedRoute(module.defaultName);
		const binding = module.local.has(name) ? {
			file,
			name
		} : fallback;
		return binding ? {
			binding,
			follow: false
		} : null;
	}
}
function resolveBinding(file, name, deps) {
	const visiting = /* @__PURE__ */ new Set();
	let fallback = null;
	while (!visiting.has(file)) {
		deps.add(file);
		const module = moduleOf(file);
		if (!module) return fallback;
		if (module.stars.length) return exportsOf(file, visiting, deps).get(name) ?? fallback;
		visiting.add(file);
		const route = exportRoute(module, file, name);
		if (!route) return fallback;
		if (!route.follow) return route.binding;
		fallback = route.binding;
		file = route.binding.file;
		name = route.binding.name;
	}
	return fallback;
}
function definingExportOf(spec, name, fromFile, deps) {
	const target = resolveFrom(fromFile, spec);
	if (!target) return null;
	const cached = derive(`binding:${target}\u0000${name}`, (dependencies) => resolveBinding(target, name, dependencies));
	if (deps) for (const dependency of cached.dependencies) deps.add(dependency);
	return cached.value ?? {
		file: target,
		name
	};
}

//#endregion
//#region src/project/components.ts
const EMPTY = {
	dir: null,
	files: /* @__PURE__ */ new Map(),
	has: () => false,
	owns: () => false
};
const cache$2 = /* @__PURE__ */ new Map();
const BARRELS = [
	"index.tsx",
	"index.ts",
	"index.jsx"
];
const SOURCE_RE = /\.(tsx|jsx|ts|js|svelte|vue)$/;
function barrelOf(dir) {
	for (const index of BARRELS) {
		const candidate = path.join(dir, index);
		if (isFile(candidate)) return candidate;
	}
	const candidate = path.join(dir, "index.js");
	if (!isFile(candidate)) return null;
	try {
		return fs.readdirSync(dir).some(isSfc) ? candidate : null;
	} catch {
		return null;
	}
}
function componentFiles(dir) {
	const files = [];
	let entries;
	try {
		entries = fs.readdirSync(dir, { withFileTypes: true });
	} catch {
		return files;
	}
	for (const entry of entries) {
		const full = path.join(dir, entry.name);
		if (entry.isFile() && SOURCE_RE.test(entry.name)) files.push(full);
		else if (entry.isDirectory()) {
			const barrel = barrelOf(full);
			if (barrel) files.push(barrel);
		}
	}
	return files.sort();
}
function signatureOf$1(files) {
	return files.map((file) => `${file}:${mtimeOf(file) ?? "missing"}`).join("|");
}
function buildIndex(dir) {
	const cached = cache$2.get(dir);
	const now = Date.now();
	if (cached && now - cached.checkedAt < 1e3) return cached.index;
	const entries = componentFiles(dir);
	if (cached && signatureFor(entries, cached.deps) === cached.signature) {
		cached.checkedAt = now;
		return cached.index;
	}
	const files = /* @__PURE__ */ new Map();
	const deps = new Set(entries);
	for (const file of entries) for (const [name, binding] of exportsOf(file, /* @__PURE__ */ new Set(), deps)) {
		const component = name === "default" ? binding.name : name;
		if (/^[A-Z]/.test(component) && !files.has(component)) files.set(component, binding.file);
	}
	const owned = new Set([...deps].map(realpath));
	const root = realpath(dir) + path.sep;
	const index = {
		dir,
		files,
		has: (name) => files.has(name),
		owns: (file) => {
			const real = realpath(file);
			return real.startsWith(root) || owned.has(real);
		}
	};
	const depList = [...deps];
	cache$2.set(dir, {
		signature: signatureFor(entries, depList),
		deps: depList,
		checkedAt: now,
		index
	});
	return index;
}
function signatureFor(entries, deps) {
	return `${entries.join(",")}||${signatureOf$1(deps)}`;
}
function componentsFor(fromFile) {
	const project = projectFor(fromFile);
	if (!project) return EMPTY;
	const dir = uiDirectory(project);
	if (!dir) return EMPTY;
	try {
		return buildIndex(dir);
	} catch {
		return EMPTY;
	}
}

//#endregion
//#region src/project/ast.ts
function walk(node, visit, parent = null) {
	if (!node || typeof node.type !== "string") return;
	visit(node, parent);
	for (const key of Object.keys(node)) {
		if (key === "parent") continue;
		const value = node[key];
		if (Array.isArray(value)) for (const child of value) walk(child, visit, node);
		else if (value && typeof value.type === "string") walk(value, visit, node);
	}
}

//#endregion
//#region src/project/sfc-template.ts
const VOID = /* @__PURE__ */ new Set([
	"area",
	"base",
	"br",
	"col",
	"embed",
	"hr",
	"img",
	"input",
	"link",
	"meta",
	"source",
	"track",
	"wbr"
]);
const blank = (text) => text.replace(/[^\n\r]/g, " ");
function markupOf(source, file) {
	if (/\.vue$/i.test(file)) {
		const open = source.match(/<template\b[^>]*>/);
		const close = source.lastIndexOf("</template");
		if (!open || open.index === void 0 || close < open.index) return "";
		const start = open.index + open[0].length;
		return blank(source.slice(0, start)) + source.slice(start, close);
	}
	return source.replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, (block) => blank(block));
}
function skipValue(text, i) {
	const quote = text[i];
	if (quote === "\"" || quote === "'" || quote === "`") {
		const end = text.indexOf(quote, i + 1);
		return end === -1 ? text.length : end + 1;
	}
	if (quote !== "{") {
		while (i < text.length && !/[\s>]/.test(text[i])) i++;
		return i;
	}
	let depth = 0;
	for (; i < text.length; i++) {
		const char = text[i];
		if (char === "\"" || char === "'" || char === "`") i = skipValue(text, i) - 1;
		else if (char === "{") depth++;
		else if (char === "}" && --depth === 0) return i + 1;
	}
	return i;
}
function templateTags(source, file) {
	const text = markupOf(source, file);
	const tags = [];
	let depth = 0;
	for (let i = 0; i < text.length; i++) {
		if (text[i] !== "<") continue;
		if (text.startsWith("<!--", i)) {
			const end = text.indexOf("-->", i);
			i = end === -1 ? text.length : end + 2;
			continue;
		}
		if (text[i + 1] === "/") {
			depth = Math.max(0, depth - 1);
			continue;
		}
		const name = text.slice(i + 1).match(/^[A-Za-z][\w:.-]*/)?.[0];
		if (!name) continue;
		const tag = {
			name,
			attributes: [],
			depth
		};
		let selfClosing = false;
		i += 1 + name.length;
		while (i < text.length) {
			while (i < text.length && /\s/.test(text[i])) i++;
			if (text[i] === ">") break;
			if (text[i] === "/") {
				selfClosing = true;
				i++;
				continue;
			}
			if (text[i] === "{") {
				const end = skipValue(text, i);
				tag.attributes.push({
					name: "",
					value: text.slice(i, end)
				});
				i = end;
				continue;
			}
			const start = i;
			while (i < text.length && !/[\s=>/]/.test(text[i])) i++;
			const attribute = {
				name: text.slice(start, i),
				value: ""
			};
			if (text[i] === "=") {
				const end = skipValue(text, i + 1);
				attribute.value = text.slice(i + 1, end);
				i = end;
			}
			if (i === start) i++;
			else tag.attributes.push(attribute);
		}
		tags.push(tag);
		if (!selfClosing && !VOID.has(name)) depth++;
	}
	return tags;
}

//#endregion
//#region src/project/wrappers.ts
const cache$1 = /* @__PURE__ */ new Map();
function signatureOf(files) {
	return files.map((file) => `${file}:${mtimeOf(file) ?? "missing"}`).join("|");
}
function indexLocalBindings(ast) {
	const bindings = /* @__PURE__ */ new Map();
	const candidates = /* @__PURE__ */ new Set();
	const aliases = [];
	for (const statement of ast.body) {
		const decl = statement.type === "ExportNamedDeclaration" || statement.type === "ExportDefaultDeclaration" ? statement.declaration : statement;
		if (decl?.type === "FunctionDeclaration" && decl.id?.name) {
			candidates.add(decl.id.name);
			bindings.set(decl.id.name, decl);
			if (statement.type === "ExportDefaultDeclaration") bindings.set("default", decl);
		} else if (decl?.type === "VariableDeclaration") for (const d of decl.declarations) {
			if (d.id?.type !== "Identifier") continue;
			candidates.add(d.id.name);
			if (d.init) bindings.set(d.id.name, d.init);
		}
		else if (decl && statement.type === "ExportDefaultDeclaration") bindings.set("default", decl);
		if (statement.type === "ExportDefaultDeclaration") candidates.add("default");
		if (statement.type === "ExportNamedDeclaration" && !statement.source) for (const spec of statement.specifiers ?? []) {
			const exported = spec.exported?.name ?? spec.exported?.value;
			if (exported) candidates.add(exported);
			aliases.push(spec);
		}
	}
	for (const spec of aliases) {
		const exported = spec.exported?.name ?? spec.exported?.value;
		const local = spec.local?.name;
		if (exported && local && exported !== local && bindings.has(local)) bindings.set(exported, bindings.get(local));
	}
	return {
		bindings,
		candidates
	};
}
function componentFunction(bindings, name) {
	let fn = bindings.get(name);
	for (let hop = 0; hop < 6 && fn; hop++) if (fn.type === "CallExpression" && fn.arguments?.[0]) fn = fn.arguments[0];
	else if (fn.type === "Identifier" && bindings.has(fn.name)) fn = bindings.get(fn.name);
	else break;
	return fn?.type === "FunctionDeclaration" || fn?.type === "FunctionExpression" || fn?.type === "ArrowFunctionExpression" ? fn : null;
}
function classNameBindings(fn) {
	const names = /* @__PURE__ */ new Set();
	const propsNames = /* @__PURE__ */ new Set();
	const param = fn.params?.[0];
	if (!param) return {
		names,
		propsNames
	};
	const pattern = param.type === "AssignmentPattern" ? param.left : param;
	if (pattern.type === "ObjectPattern") {
		for (const prop of pattern.properties) {
			if (prop.type !== "Property") continue;
			if ((prop.key?.name ?? prop.key?.value) !== "className") continue;
			const value = prop.value?.type === "AssignmentPattern" ? prop.value.left : prop.value;
			if (value?.type === "Identifier") names.add(value.name);
		}
		if (!names.size) {
			for (const prop of pattern.properties) if (prop.type === "RestElement" && prop.argument?.type === "Identifier") propsNames.add(prop.argument.name);
		}
	} else if (pattern.type === "Identifier") propsNames.add(pattern.name);
	return {
		names,
		propsNames
	};
}
function forwardsClassName(expr, names, propsNames) {
	let found = false;
	walk(expr, (node) => {
		if (found) return;
		if (node.type === "Identifier" && names.has(node.name)) found = true;
		if (node.type === "MemberExpression" && node.object?.type === "Identifier" && propsNames.has(node.object.name) && node.property?.name === "className") found = true;
		if (node.type === "JSXSpreadAttribute" && node.argument?.type === "Identifier" && propsNames.has(node.argument.name)) found = true;
	});
	return found;
}
function sfcClassBindings(ast, vue) {
	const names = /* @__PURE__ */ new Set();
	const propsNames = new Set(vue ? ["$props", "$attrs"] : []);
	let declaresClass = false;
	const isPropsCall = (node) => {
		while (node?.type?.startsWith("TS") && node.expression) node = node.expression;
		if (node?.type !== "CallExpression" || node.callee?.type !== "Identifier") return false;
		if (node.callee.name === "withDefaults") return isPropsCall(node.arguments[0]);
		return node.callee.name === "$props" || node.callee.name === "defineProps";
	};
	walk(ast, (node) => {
		if (node.type === "CallExpression" && isPropsCall(node)) walk(node, (inner) => {
			const key = inner.key?.name ?? inner.key?.value;
			if ((inner.type === "TSPropertySignature" || inner.type === "Property") && key === "class") declaresClass = true;
		});
		if (node.type !== "VariableDeclarator" || !isPropsCall(node.init)) return;
		if (node.id.type === "Identifier") {
			propsNames.add(node.id.name);
			return;
		}
		if (node.id.type !== "ObjectPattern") return;
		const rests = [];
		for (const prop of node.id.properties) {
			if (prop.type === "RestElement" && prop.argument?.type === "Identifier") rests.push(prop.argument.name);
			if (prop.type !== "Property") continue;
			if ((prop.key?.name ?? prop.key?.value) !== "class") continue;
			const value = prop.value?.type === "AssignmentPattern" ? prop.value.left : prop.value;
			if (value?.type === "Identifier") names.add(value.name);
		}
		if (!names.size) for (const rest of rests) propsNames.add(rest);
	});
	return {
		names,
		propsNames,
		declaresClass
	};
}
const escapeName = (name) => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
function tagForwardsClass(tag, names, propsNames) {
	const mentions = (value) => [...names].some((name) => new RegExp(`(?<![\\w$.])${escapeName(name)}(?![\\w$])`).test(value)) || [...propsNames].some((name) => new RegExp(`(?<![\\w$.])${escapeName(name)}\\.class(?![\\w$])`).test(value));
	return tag.attributes.some(({ name, value }) => {
		if (name === "class" || name === ":class" || name === "v-bind:class") return mentions(value);
		const spread = name === "" ? value.match(/^\{\s*\.\.\.\s*([\w$]+)\s*\}$/)?.[1] : name === "v-bind" ? value.replace(/^["']|["']$/g, "").trim() : void 0;
		return spread !== void 0 && propsNames.has(spread);
	});
}
function sfcForwardingTags(source, file, ast) {
	const vue = /\.vue$/i.test(file);
	const { names, propsNames, declaresClass } = sfcClassBindings(ast, vue);
	const tags = templateTags(source, file);
	const forwarding = tags.filter((tag) => tagForwardsClass(tag, names, propsNames));
	const roots = tags.filter((tag) => tag.depth === 0);
	if (vue && !declaresClass && roots.length === 1 && !/inheritAttrs\s*:\s*false/.test(source) && !forwarding.includes(roots[0])) forwarding.unshift(roots[0]);
	return forwarding;
}
function jsxElementName(node) {
	const name = node.name;
	if (name?.type === "JSXIdentifier") return {
		root: name.name,
		property: null
	};
	if (name?.type === "JSXMemberExpression") return {
		root: name.object?.name,
		property: name.property?.name ?? ""
	};
	return null;
}
function build(file, patterns, visiting, deps, parsedAst) {
	const wrappers = /* @__PURE__ */ new Map();
	let complete = true;
	deps.add(file);
	const sfc = isSfc(file);
	let ast = sfc ? void 0 : parsedAst;
	let source = "";
	if (!ast) {
		try {
			source = fs.readFileSync(file, "utf-8");
		} catch {
			return {
				wrappers,
				complete
			};
		}
		if (!sfc && !source.includes("className") && !source.includes("...")) return {
			wrappers,
			complete
		};
		try {
			ast = parseSource(source, file);
		} catch {
			return {
				wrappers,
				complete
			};
		}
	}
	const imports = /* @__PURE__ */ new Map();
	for (const statement of ast.body) {
		if (statement.type !== "ImportDeclaration") continue;
		const source = statement.source?.value;
		if (typeof source !== "string") continue;
		for (const spec of statement.specifiers ?? []) {
			const local = spec.local?.name;
			if (!local) continue;
			const original = spec.type === "ImportSpecifier" ? spec.imported?.name ?? spec.imported?.value ?? local : spec.type === "ImportDefaultSpecifier" ? "default" : local;
			imports.set(local, {
				source,
				original,
				namespace: spec.type === "ImportNamespaceSpecifier"
			});
		}
	}
	const index = componentsFor(file);
	const { bindings, candidates } = indexLocalBindings(ast);
	const localVisiting = /* @__PURE__ */ new Set();
	const targetOf = (element) => targetOfName(jsxElementName(element));
	const targetOfName = (name) => {
		if (!name?.root) return null;
		const imported = imports.get(name.root);
		if (!imported) {
			if (name.property !== null) return null;
			if (index.has(name.root)) return {
				component: name.root,
				file: index.files.get(name.root) ?? null
			};
			return candidates.has(name.root) ? resolveDeclared(name.root) : null;
		}
		const importedName = importNameOf(imported, name.root, name.property);
		const binding = importedName.exportName ? definingExportOf(importedName.source, importedName.exportName, file, deps) : null;
		const component = componentFromImport(index, binding, importedName, patterns);
		if (component) return component;
		if (!binding) {
			complete = false;
			return index.has(importedName.name) ? {
				component: importedName.name,
				file: index.files.get(importedName.name) ?? null
			} : null;
		}
		if (binding.file === file || NODE_MODULES.test(binding.file)) return null;
		if (importedName.suffix) return null;
		if (visiting.has(binding.file)) {
			complete = false;
			return null;
		}
		const result = lookup(binding.file, binding.name, patterns, visiting, deps);
		if (!result.complete) complete = false;
		return result.target;
	};
	const resolveDeclared = (name) => {
		const cached = wrappers.get(name);
		if (cached !== void 0) return cached;
		if (localVisiting.has(name)) {
			complete = false;
			return null;
		}
		localVisiting.add(name);
		let target = null;
		const fn = componentFunction(bindings, name);
		if (fn) {
			const { names, propsNames } = classNameBindings(fn);
			if (names.size || propsNames.size) walk(fn.body, (node) => {
				if (target || node.type !== "JSXOpeningElement") return;
				if (node.attributes?.some((attr) => attr.type === "JSXAttribute" && attr.name?.name === "className" && forwardsClassName(attr.value, names, propsNames) || attr.type === "JSXSpreadAttribute" && forwardsClassName(attr, names, propsNames))) target = targetOf(node);
			});
		}
		localVisiting.delete(name);
		wrappers.set(name, target);
		return target;
	};
	for (const name of candidates) if (name === "default" || /^[A-Z]/.test(name)) resolveDeclared(name);
	if (sfc) {
		let target = null;
		for (const tag of sfcForwardingTags(source, file, ast)) {
			const [root, ...rest] = tag.name.split(".");
			const pascal = root.includes("-") ? sfcNameOf(root) : root;
			target = targetOfName({
				root: imports.has(root) ? root : pascal,
				property: rest.length ? rest.join(".") : null
			});
			if (target) break;
		}
		wrappers.set(sfcNameOf(file), target);
	}
	return {
		wrappers,
		complete
	};
}
function lookup(file, exportName, patterns, visiting, deps, parsedAst) {
	deps?.add(file);
	if (mtimeOf(file) === null) return {
		target: null,
		complete: false
	};
	const key = `${file}|${patterns.map((p) => p.source).join(",")}`;
	const cached = cache$1.get(key);
	const now = Date.now();
	if (cached && (now - cached.checkedAt < 1e3 || signatureOf(cached.deps) === cached.signature)) {
		if (now - cached.checkedAt >= 1e3) cached.checkedAt = now;
		if (deps) for (const dep of cached.deps) deps.add(dep);
		return {
			target: cached.wrappers.get(exportName) ?? null,
			complete: true
		};
	}
	visiting.add(file);
	const own = /* @__PURE__ */ new Set();
	const { wrappers, complete } = build(file, patterns, visiting, own, parsedAst);
	visiting.delete(file);
	if (deps) for (const dep of own) deps.add(dep);
	const depList = [...own];
	if (complete) cache$1.set(key, {
		deps: depList,
		signature: signatureOf(depList),
		checkedAt: now,
		wrappers
	});
	return {
		target: wrappers.get(exportName) ?? null,
		complete
	};
}
function wrapperTargetOf(file, exportName, patterns = [], parsedAst) {
	return lookup(file, exportName, patterns, /* @__PURE__ */ new Set(), void 0, parsedAst).target;
}

//#endregion
//#region src/rules/messages.ts
const LISTED = 12;
const listed = /* @__PURE__ */ new WeakMap();
const PLACEHOLDER = /\{\{\s*([^{}|]+?)\s*(?:\|([^{}]*))?\}\}/g;
const MESSAGE_KEYS = /* @__PURE__ */ new Set([
	...[
		"className",
		"property",
		"component",
		"suggestions",
		"file"
	],
	"category",
	"variants",
	"wrapper",
	"sizes",
	"entries",
	"tokens",
	"suggestion",
	"replacement",
	"attribute",
	"value",
	"around",
	"where",
	"variantsSuffix"
]);
function fileOf(context) {
	return context.physicalFilename ?? context.getFilename?.() ?? "";
}
function displayPath(file, context) {
	const cwd = context.cwd ?? process.cwd();
	return memoize(`display-path:${cwd}\u0000${file}`, () => {
		const relative = path.relative(cwd, file);
		return (relative.startsWith("..") ? file : relative).replace(/\\/g, "/");
	});
}
function listTokens(declared) {
	const cached = listed.get(declared);
	if (cached !== void 0) return cached;
	const text = formatTokens(declared);
	listed.set(declared, text);
	return text;
}
function formatTokens(declared) {
	const sorted = [...declared].sort((a, b) => {
		return (a.endsWith("-foreground") ? 1 : 0) - (b.endsWith("-foreground") ? 1 : 0) || a.localeCompare(b);
	});
	const shown = sorted.slice(0, LISTED);
	const rest = sorted.length - shown.length;
	return rest > 0 ? `${shown.join(", ")} (+${rest} more)` : shown.join(", ");
}
function noteFor(context) {
	const note = context.settings?.shadcn?.note;
	if (note == null) return "";
	if (typeof note !== "string") {
		warnOnce("settings:note", "settings.shadcn.note must be a string; it is ignored.");
		return "";
	}
	return note.trim();
}
function checkMessage(message, label) {
	for (const [, key] of message.matchAll(PLACEHOLDER)) {
		if (MESSAGE_KEYS.has(key) || !/^[A-Za-z_$][\w$]*$/.test(key)) continue;
		let nearest = null;
		let closest = 3;
		for (const candidate of MESSAGE_KEYS) {
			const d = editDistance(key.toLowerCase(), candidate.toLowerCase());
			if (d < closest) {
				nearest = candidate;
				closest = d;
			} else if (d === closest) nearest = null;
		}
		if (nearest) warnOnce(`placeholder:${JSON.stringify([label, key])}`, `Unknown message placeholder "{{${key}}}" in ${label.startsWith("shadcn/") ? label : `contract "${label}"`}. Did you mean "{{${nearest}}}"? It will remain literal.`);
	}
}
function interpolate(text, data) {
	return text.replace(PLACEHOLDER, (match, key, fallback) => {
		if (!Object.hasOwn(data, key)) return match;
		const value = data[key] == null ? "" : String(data[key]);
		return value !== "" ? value : fallback?.trim() ?? "";
	});
}
function ruleMessageFor(rule, option) {
	if (option == null) return "";
	if (typeof option !== "string") {
		warnOnce(`${rule}:message`, `${rule}: the message option must be a string; it is ignored.`);
		return "";
	}
	checkMessage(option, rule);
	return option.trim();
}
function withUniversalSlots(data) {
	const first = (...keys) => {
		for (const key of keys) {
			const value = data[key];
			if (value != null && String(value) !== "") return String(value);
		}
		return "";
	};
	return {
		...data,
		className: first("className") || (data.attribute ? `${data.attribute}="${data.value ?? ""}"` : ""),
		property: first("property"),
		component: first("component"),
		suggestions: first("suggestions", "replacement", "suggestion"),
		file: first("file")
	};
}
function reporter(context, messages, options = {}) {
	const note = noteFor(context);
	const ruleMessage = ruleMessageFor(options.rule ?? "shadcn", options.message);
	return (descriptor, override) => {
		const text = typeof override === "string" && override.trim() !== "" ? override.trim() : ruleMessage;
		if (!text && !note) {
			context.report(descriptor);
			return;
		}
		const data = withUniversalSlots(descriptor.data ?? {});
		const { messageId, ...rest } = descriptor;
		const parts = [interpolate(text || (messages[messageId] ?? ""), data), note].filter((p) => p !== "");
		context.report({
			...rest,
			message: parts.join(" ")
		});
	};
}

//#endregion
//#region src/rules/settings.ts
const SHARED = [
	"componentImports",
	"ignoreImports",
	"mergeFunctions",
	"variantFunctions"
];
function strings(value, key) {
	const list = Array.isArray(value) ? value : value == null ? [] : [value];
	if (!list.every((v) => typeof v === "string")) {
		warnOnce(`settings:${key}`, `settings.shadcn.${key} must be a string or an array of strings; it is ignored.`);
		return null;
	}
	return list;
}
function escapeRegExp$1(text) {
	return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
function withSettings(context, options) {
	const settings = context.settings?.shadcn;
	if (!settings || typeof settings !== "object") return options;
	const merged = { ...options };
	for (const key of SHARED) {
		if (merged[key] !== void 0 || settings[key] === void 0) continue;
		const list = strings(settings[key], key);
		if (list) merged[key] = list;
	}
	if (settings.ui !== void 0) {
		const prefixes = strings(settings.ui, "ui") ?? [];
		if (prefixes.length) merged.componentImports = [...merged.componentImports ?? [], ...prefixes.map((prefix) => `^${escapeRegExp$1(prefix)}(/|$)`)];
	}
	return merged;
}

//#endregion
//#region src/sites/readers/jsx.ts
function attributeNameOf(attribute) {
	const name = attribute?.name;
	if (name?.type === "JSXNamespacedName") return `${name.namespace?.name}:${name.name?.name}`;
	return typeof name?.name === "string" ? name.name : "";
}
function jsxNameText(jsxName) {
	if (jsxName?.type === "JSXMemberExpression") return `${jsxNameText(jsxName.object)}.${jsxName.property?.name ?? ""}`;
	return jsxName?.name ?? "";
}
function jsxRootOf(jsxName) {
	return jsxName?.type === "JSXMemberExpression" ? jsxName.object?.name : jsxName?.name;
}
function jsxElementNameOf(name) {
	if (!name) return null;
	const root = jsxRootOf(name);
	const member = name.type === "JSXMemberExpression";
	return {
		root: typeof root === "string" ? root : "",
		property: member ? name.property?.name ?? "" : null,
		text: jsxNameText(name),
		component: member || name.type === "JSXIdentifier" && /^[A-Z]/.test(name.name)
	};
}
function propsSpreadNameOf(fn) {
	const param = fn.params?.[0];
	if (param?.type === "Identifier") return param.name;
	if (param?.type === "ObjectPattern") {
		const rest = param.properties.find((p) => p.type === "RestElement");
		if (rest?.argument?.type === "Identifier") return rest.argument.name;
	}
	return null;
}
function renderedElementOf(element) {
	const expression = (element.openingElement?.attributes ?? []).find((candidate) => candidate.type === "JSXAttribute" && candidate.name?.name === "render")?.value?.expression;
	if (expression?.type === "JSXElement") return expression;
	if (expression?.type !== "ArrowFunctionExpression") return void 0;
	const body = expression.body;
	const spread = propsSpreadNameOf(expression);
	if (body?.type !== "JSXElement" || !spread) return void 0;
	return (body.openingElement.attributes ?? []).some((candidate) => candidate.type === "JSXSpreadAttribute" && candidate.argument?.type === "Identifier" && candidate.argument.name === spread) ? body : void 0;
}
const jsxReader = {
	attributes: ["JSXAttribute"],
	spreads: ["JSXSpreadAttribute"],
	attributeName: attributeNameOf,
	attributeValue: (node) => node.value,
	spreadArgument: (node) => node.argument,
	elementOf(node) {
		const opening = node?.parent;
		return opening?.type === "JSXOpeningElement" ? opening.parent : null;
	},
	nameOf: (element) => jsxElementNameOf(element?.openingElement?.name),
	parentElementOf(element) {
		for (let node = element?.parent; node; node = node.parent) if (node.type === "JSXElement") return node;
		return null;
	},
	renderedElementOf
};

//#endregion
//#region src/sites/readers/svelte.ts
const templates = /* @__PURE__ */ new WeakMap();
function templateOf(attribute) {
	let template = templates.get(attribute);
	if (template) return template;
	const parts = attribute.value;
	template = {
		type: "TemplateLiteral",
		quasis: [],
		expressions: [],
		range: [parts[0].range[0], parts[parts.length - 1].range[1]],
		loc: {
			start: parts[0].loc.start,
			end: parts[parts.length - 1].loc.end
		},
		parent: attribute
	};
	let text = "";
	let first = null;
	let last = null;
	const flush = (at) => {
		const from = first ?? at;
		const to = last ?? at;
		template.quasis.push({
			type: "TemplateElement",
			value: {
				cooked: text,
				raw: text
			},
			tail: false,
			range: first ? [from.range[0], to.range[1]] : [at.range[0], at.range[0]],
			loc: first ? {
				start: from.loc.start,
				end: to.loc.end
			} : {
				start: at.loc.start,
				end: at.loc.start
			},
			parent: template
		});
		text = "";
		first = last = null;
	};
	for (const part of parts) if (part.type === "SvelteLiteral") {
		text += part.value;
		first ??= part;
		last = part;
	} else {
		flush(part);
		template.expressions.push(part.expression);
	}
	flush(parts[parts.length - 1]);
	template.quasis[template.quasis.length - 1].tail = true;
	templates.set(attribute, template);
	return template;
}
function valueOf(attribute) {
	const parts = attribute?.value ?? [];
	if (!parts.length) return null;
	if (parts.length === 1) return parts[0];
	return templateOf(attribute);
}
function nameText(name) {
	if (name?.type === "SvelteMemberExpressionName") return `${nameText(name.object)}.${name.property?.name ?? ""}`;
	return name?.name ?? "";
}
const svelteReader = {
	attributes: ["SvelteAttribute"],
	spreads: ["SvelteSpreadAttribute"],
	classObjects: true,
	staticStyles: true,
	attributeName: (node) => typeof node?.key?.name === "string" ? node.key.name : "",
	attributeValue: valueOf,
	spreadArgument: (node) => node.argument,
	elementOf(node) {
		const element = node?.parent?.parent;
		return element?.type === "SvelteElement" ? element : null;
	},
	nameOf(element) {
		const name = element?.name;
		if (!name) return null;
		const member = name.type === "SvelteMemberExpressionName";
		const root = member ? name.object?.name : name.name;
		return {
			root: typeof root === "string" ? root : "",
			property: member ? name.property?.name ?? "" : null,
			text: nameText(name),
			component: element.kind === "component"
		};
	},
	parentElementOf(element) {
		for (let node = element?.parent; node; node = node.parent) if (node.type === "SvelteElement") return node;
		return null;
	},
	extraSites: { SvelteDirective(node) {
		if (node.kind !== "Class") return null;
		const name = node.key?.name;
		return typeof name?.name === "string" ? {
			names: [{
				value: name.name,
				node: name
			}],
			anchor: node
		} : null;
	} },
	styleProperties: { SvelteStyleDirective(node) {
		const property = node.key?.name?.name;
		return typeof property === "string" ? {
			property,
			value: valueOf(node) ?? node.key.name
		} : null;
	} }
};

//#endregion
//#region src/sites/readers/vue.ts
function bindingOf(node) {
	const key = node?.key;
	return node?.directive && key?.name?.name === "bind" ? key : null;
}
function pascalCase(name) {
	return name.split("-").filter(Boolean).map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join("");
}
const vueReader = {
	attributes: ["VAttribute"],
	spreads: ["VAttribute"],
	classObjects: true,
	staticStyles: true,
	attributeName(node) {
		if (!node?.directive) return typeof node?.key?.name === "string" ? node.key.name : "";
		const argument = bindingOf(node)?.argument;
		return argument?.type === "VIdentifier" ? argument.name : "";
	},
	attributeValue: (node) => node?.value ?? null,
	spreadArgument(node) {
		const binding = bindingOf(node);
		return binding && !binding.argument ? node.value?.expression ?? null : null;
	},
	elementOf(node) {
		const element = node?.parent?.parent;
		return element?.type === "VElement" ? element : null;
	},
	nameOf(element) {
		const text = element?.rawName ?? "";
		if (!text) return null;
		const [root, ...rest] = text.split(".");
		const kebab = root.includes("-");
		return {
			root,
			property: rest.length ? rest.join(".") : null,
			text,
			component: rest.length > 0 || kebab || /^[A-Z]/.test(root),
			...kebab ? { alias: pascalCase(root) } : {}
		};
	},
	parentElementOf(element) {
		for (let node = element?.parent; node; node = node.parent) if (node.type === "VElement" && node.rawName !== "template") return node;
		return null;
	},
	variableOf(node, context) {
		let container = node;
		while (container && container.type !== "VExpressionContainer") container = container.parent;
		if ((container?.references?.find((r) => r.id === node))?.variable) return null;
		const scopes = context.sourceCode?.scopeManager?.scopes ?? [];
		return (scopes.find((s) => s.type === "module") ?? scopes[0])?.set?.get(node.name) ?? null;
	}
};

//#endregion
//#region src/sites/readers/index.ts
const readers = [
	jsxReader,
	svelteReader,
	vueReader
];
function readerFor(context) {
	const services = context?.sourceCode?.parserServices;
	if (services?.isSvelte) return svelteReader;
	if (typeof services?.defineTemplateBodyVisitor === "function") return vueReader;
	return jsxReader;
}
const CONTAINERS = {
	JSXExpressionContainer: "JSXAttribute",
	SvelteMustacheTag: "SvelteAttribute",
	VExpressionContainer: "VAttribute"
};
const LITERALS = /* @__PURE__ */ new Set([
	"Literal",
	"SvelteLiteral",
	"VLiteral"
]);
function addVisitor(visitors, type, visit) {
	const existing = visitors[type];
	visitors[type] = existing ? (node) => {
		existing(node);
		visit(node);
	} : visit;
}
function isContainer(node) {
	return typeof node?.type === "string" && node.type in CONTAINERS;
}
function attributeOfContainer(container) {
	const attribute = container?.parent;
	return attribute && CONTAINERS[container.type] === attribute.type ? attribute : null;
}
function attributeNameIn(attribute) {
	const reader = readers.find((r) => r.attributes.includes(attribute?.type));
	return reader ? reader.attributeName(attribute) : "";
}
function isMarkupLiteral(node) {
	return node?.type !== "Literal" && LITERALS.has(node?.type);
}
function staticStringOf(value) {
	const node = isContainer(value) ? value.expression : value;
	return LITERALS.has(node?.type) && typeof node.value === "string" ? node.value : null;
}
function withTemplates(rule) {
	return {
		...rule,
		create(context) {
			const visitors = rule.create(context);
			const services = context.sourceCode?.parserServices;
			const define = services?.defineTemplateBodyVisitor;
			if (typeof define === "function") return define({ ...visitors }, { ...visitors });
			if (!services?.isSvelte && isSfc(fileOf(context) ?? "")) warnOnce("templates:unread", "Templates in .svelte and .vue files are read under ESLint with svelte-eslint-parser or vue-eslint-parser. This run has no template parser, so only their script blocks are linted. See https://github.com/shadcn-ui/lint/blob/main/docs/vue.md and https://github.com/shadcn-ui/lint/blob/main/docs/svelte.md.");
			return visitors;
		}
	};
}

//#endregion
//#region src/sites/collect.ts
const DEFAULT_MERGE_FUNCTIONS = [
	"cn",
	"cx",
	"clsx",
	"cva",
	"tv",
	"twMerge",
	"twJoin",
	"classNames"
];
const DEFAULT_VARIANT_FUNCTIONS = ["cva", "tv"];
const CLASS_ATTRIBUTE = /^(class:list|[^:]*class(name)?s?)$/i;
function isClassAttribute(name) {
	return CLASS_ATTRIBUTE.test(name);
}
const regexps = /* @__PURE__ */ new Map();
function regexpOf(pattern) {
	let re = regexps.get(pattern);
	if (!re) {
		re = new RegExp(pattern);
		regexps.set(pattern, re);
	}
	return re;
}
function createComponentTracker(context, options = {}) {
	const filename = fileOf(context);
	const index = componentsFor(filename);
	const patterns = (options.componentImports ?? []).map(regexpOf);
	const ignored = (options.ignoreImports ?? []).map(regexpOf);
	const imports = /* @__PURE__ */ new Map();
	const skipped = /* @__PURE__ */ new Set();
	const bindings = /* @__PURE__ */ new Map();
	const wrappers = /* @__PURE__ */ new Map();
	const bindingOf = (root, name) => {
		const key = `${root}:${name}`;
		const cached = bindings.get(key);
		if (cached !== void 0) return cached;
		const source = imports.get(root)?.source;
		const binding = source && filename ? definingExportOf(source, name, filename) : null;
		bindings.set(key, binding);
		return binding;
	};
	const wrapperOf = (key, binding, local) => {
		const cached = wrappers.get(key);
		if (cached !== void 0) return cached;
		let target = null;
		if (binding) {
			if (binding.file !== filename && !NODE_MODULES.test(binding.file)) target = wrapperTargetOf(binding.file, binding.name, patterns);
		} else if (local && filename && /^[A-Z]/.test(local)) target = wrapperTargetOf(filename, local, patterns, context.sourceCode?.ast);
		wrappers.set(key, target);
		return target;
	};
	const resolveName = (element) => {
		if (!element) return null;
		const root = element.alias && !imports.has(element.root) && imports.has(element.alias) ? element.alias : element.root;
		if (!root || skipped.has(root)) return null;
		const property = element.property;
		const imported = imports.get(root);
		if (imported) {
			const importedName = importNameOf(imported, root, property);
			if (imported.namespace && property === null) importedName.name = root;
			const { exportName, name } = importedName;
			const binding = exportName ? bindingOf(root, exportName) : null;
			const component = componentFromImport(index, binding, importedName, patterns);
			if (component) return {
				...component,
				wrapper: null
			};
			if (binding) {
				if (NODE_MODULES.test(binding.file)) return null;
				if (property !== null && !imported.namespace) return null;
				const target = wrapperOf(`${root}.${exportName}`, binding, null);
				if (!target) return null;
				const wrapper = property === null ? name : `${root}.${property}`;
				return {
					component: target.component,
					file: target.file,
					wrapper
				};
			}
			if (index.has(name) || index.has(imported.original)) return {
				component: name,
				file: index.files.get(name) ?? index.files.get(imported.original) ?? null,
				wrapper: null
			};
			return null;
		}
		const name = property === null ? root : `${root}${property}`;
		if (index.has(name)) return {
			component: name,
			file: index.files.get(name) ?? null,
			wrapper: null
		};
		if (property !== null) return null;
		const target = wrapperOf(root, null, root);
		return target ? {
			component: target.component,
			file: target.file,
			wrapper: name
		} : null;
	};
	return {
		collectImport(node) {
			const source = node.source?.value;
			if (typeof source !== "string") return;
			const matchesIgnore = ignored.some((p) => p.test(source));
			for (const spec of node.specifiers ?? []) {
				const local = spec.local?.name;
				if (!local) continue;
				const original = spec.type === "ImportSpecifier" ? spec.imported?.name ?? spec.imported?.value ?? local : spec.type === "ImportDefaultSpecifier" ? "default" : local;
				imports.set(local, {
					source,
					original,
					namespace: spec.type === "ImportNamespaceSpecifier"
				});
				if (matchesIgnore) skipped.add(local);
			}
		},
		resolve: (jsxName) => resolveName(jsxElementNameOf(jsxName)),
		resolveName
	};
}
function findVariable(scope, name) {
	for (let s = scope; s; s = s.upper) {
		const variable = s.set?.get(name);
		if (variable) return variable;
	}
	return null;
}
function variableOf(node, context) {
	const scope = context.sourceCode?.getScope?.(node);
	return (scope ? findVariable(scope, node.name) : null) ?? readerFor(context).variableOf?.(node, context) ?? null;
}
function referenceExpression(node) {
	while (node.parent?.expression === node && [
		"TSAsExpression",
		"TSNonNullExpression",
		"TSSatisfiesExpression"
	].includes(node.parent.type)) node = node.parent;
	return node;
}
function isMutated(variable) {
	return (variable.references ?? []).some((ref) => {
		const id = referenceExpression(ref.identifier);
		const parent = id?.parent;
		if (parent?.type === "MemberExpression" && parent.object === id) {
			let member = referenceExpression(parent);
			while (member.parent?.type === "MemberExpression" && member.parent.object === member) member = referenceExpression(member.parent);
			while (member.parent?.type === "Property" && member.parent.value === member && member.parent.parent?.type === "ObjectPattern" || member.parent?.type === "ArrayPattern" || member.parent?.type === "RestElement" && member.parent.argument === member || member.parent?.type === "AssignmentPattern" && member.parent.left === member) member = member.parent.type === "Property" ? member.parent.parent : member.parent;
			const outer = member.parent;
			return outer?.type === "AssignmentExpression" && outer.left === member || outer?.type === "UpdateExpression" || outer?.type === "UnaryExpression" && outer.operator === "delete";
		}
		return parent?.type === "CallExpression" && parent.callee?.type === "MemberExpression" && parent.callee.object?.name === "Object" && parent.callee.property?.name === "assign" && parent.arguments?.[0] === id;
	});
}
const helperNames = /* @__PURE__ */ new WeakMap();
function helperNamesOf(context) {
	let names = helperNames.get(context);
	if (!names) {
		const options = withSettings(context, context.options?.[0] ?? {});
		names = [
			...DEFAULT_MERGE_FUNCTIONS,
			...options.mergeFunctions ?? [],
			...options.variantFunctions ?? []
		];
		helperNames.set(context, names);
	}
	return names;
}
function isEscaped(variable, context) {
	return (variable.references ?? []).some((ref) => {
		if (!ref.isRead?.()) return false;
		let value = referenceExpression(ref.identifier);
		let parent = value.parent;
		while (parent?.type === "ConditionalExpression" && parent.test !== value || parent?.type === "LogicalExpression" || parent?.type === "SequenceExpression" && parent.expressions.at(-1) === value) {
			value = referenceExpression(parent);
			parent = value.parent;
		}
		if (context) {
			const attribute = attributeOfContainer(parent);
			if (attribute && (attributeNameIn(attribute) === "style" || isClassAttribute(attributeNameIn(attribute)))) return false;
			let container = value;
			let outer = parent;
			while (outer?.type === "Property" && outer.value === container && outer.parent?.type === "ObjectExpression") {
				container = outer.parent;
				outer = container.parent;
			}
			if (outer?.type === "CallExpression" && outer.arguments.includes(container) && outer.callee.type === "Identifier" && helperNamesOf(context).includes(outer.callee.name)) return false;
		}
		return parent?.type === "VariableDeclarator" && parent.id.type === "Identifier" && parent.init === value || parent?.type === "AssignmentExpression" && ["Identifier", "MemberExpression"].includes(parent.left.type) && parent.right === value || (parent?.type === "CallExpression" || parent?.type === "NewExpression") && parent.arguments.includes(value) || parent?.type === "ReturnStatement" && parent.argument === value || parent?.type === "ArrowFunctionExpression" && parent.body === value || parent?.type === "Property" && parent.value === value && parent.parent?.type === "ObjectExpression" || parent?.type === "ArrayExpression" || attributeOfContainer(parent) !== null;
	});
}
function isWritten(variable) {
	return variable.references?.some((ref) => ref.isWrite?.() && !ref.init) || isMutated(variable);
}
function patternStepsOf(binding, pattern) {
	const steps = [];
	let node = binding;
	while (node !== pattern) {
		const parent = node?.parent;
		if (parent?.type === "ArrayPattern") {
			steps.unshift({ index: parent.elements.indexOf(node) });
			node = parent;
		} else if (parent?.type === "Property" && parent.value === node && parent.parent?.type === "ObjectPattern") {
			const key = keyName$1(parent);
			if (key === null) return null;
			steps.unshift({ key });
			node = parent.parent;
		} else return null;
	}
	return steps;
}
function projectStatic(init, steps) {
	let node = init;
	let i = 0;
	for (; i < steps.length; i++) {
		const value = unwrapTs(node);
		const step = steps[i];
		if ("index" in step && value?.type === "ArrayExpression") {
			if (value.elements.slice(0, step.index + 1).some((el) => el?.type === "SpreadElement")) break;
			const element = value.elements[step.index];
			if (!element) break;
			node = element;
		} else if ("key" in step && value?.type === "ObjectExpression") {
			if (value.properties.some((p) => p.type !== "Property")) break;
			const found = value.properties.filter((p) => keyName$1(p) === step.key);
			if (!found.length) break;
			node = found[found.length - 1].value;
		} else break;
	}
	return {
		init: node,
		steps: steps.slice(i)
	};
}
function resolveIdentifier(node, context, path) {
	const variable = variableOf(node, context);
	if (!variable || path.has(variable)) return null;
	const def = variable.defs?.[0];
	if (!def || def.type !== "Variable" || !def.node?.init) return null;
	if (isWritten(variable)) return null;
	let init = def.node.init;
	let steps = [];
	if (def.name !== def.node.id) {
		const route = patternStepsOf(def.name, def.node.id);
		if (!route) return null;
		({init, steps} = projectStatic(init, route));
	}
	if (unwrapTs(init)?.type === "ObjectExpression" && isEscaped(variable, context)) return null;
	return {
		init,
		variable,
		steps
	};
}
function isPropsCall(node) {
	const call = unwrapTs(node);
	if (call?.type !== "CallExpression" || call.callee?.type !== "Identifier") return false;
	if (call.callee.name === "withDefaults") return isPropsCall(call.arguments[0]);
	return call.callee.name === "$props" || call.callee.name === "defineProps";
}
function parameterOf(node, context) {
	const variable = variableOf(node, context);
	const def = variable?.defs?.[0];
	if (!def) return null;
	const received = def.type === "Variable" && isPropsCall(def.node?.init);
	if (def.type !== "Parameter" && !received) return null;
	let binding = def.name;
	let fallback = null;
	if (binding.parent?.type === "AssignmentPattern") {
		binding = binding.parent;
		fallback = binding.right;
	}
	let key = "*";
	let pattern = binding;
	if (binding.parent?.type === "Property") {
		key = keyName$1(binding.parent) ?? "";
		pattern = binding.parent.parent;
	} else if (binding.parent?.type === "RestElement") pattern = binding.parent.parent;
	const parameter = pattern.parent?.type === "AssignmentPattern" ? pattern.parent : pattern;
	if (received ? parameter !== def.node.id : !def.node.params?.includes(parameter)) return null;
	const objectDefault = parameter.type === "AssignmentPattern" ? parameter : null;
	return {
		variable,
		key,
		fallback: key === "*" ? null : fallback,
		objectDefault,
		received
	};
}
function namesProp(parameter, key, name) {
	return key === name || parameter.received && name === "className" && key === "class";
}
function forwardedPropOf(node, context, name) {
	if (node?.type === "Identifier") {
		const parameter = parameterOf(node, context);
		return parameter && namesProp(parameter, parameter.key, name) && !isWritten(parameter.variable) ? parameter : null;
	}
	if (node?.type !== "MemberExpression") return null;
	const key = node.computed ? staticKey(node.property) : node.property?.name;
	const object = unwrapTs(node.object);
	if (object?.type !== "Identifier") return null;
	if (key !== name && !(name === "className" && key === "class")) return null;
	const parameter = parameterOf(object, context);
	return parameter?.key === "*" && namesProp(parameter, key, name) && !isWritten(parameter.variable) && (parameter.received || !isEscaped(parameter.variable)) ? parameter : null;
}
function isForwardedProp(node, context, name) {
	return forwardedPropOf(node, context, name) !== null;
}
function forwardedValuesOf(node, context, name, path) {
	const parameter = forwardedPropOf(node, context, name);
	if (!parameter) return null;
	const alternatives = [];
	if (!path.has(parameter.variable)) {
		if (parameter.fallback) alternatives.push({ value: parameter.fallback });
		if (parameter.objectDefault) {
			const defaultsPath = new Set(path).add(parameter.variable);
			const object = resolveObject(parameter.objectDefault.right, context, defaultsPath);
			const found = object ? resolveProperty(object, name, context, defaultsPath) : {
				value: void 0,
				uncertain: true
			};
			if (found.uncertain) alternatives.push({ unresolved: parameter.objectDefault });
			else if (found.value) alternatives.push({ value: found.value });
		}
	}
	return {
		variable: parameter.variable,
		alternatives
	};
}
function keyName$1(prop) {
	if (prop.computed) return staticKey(prop.key);
	if (prop.key?.type === "Identifier") return prop.key.name;
	if (prop.key?.type === "Literal") return String(prop.key.value);
	return null;
}
function staticKey(key) {
	if (key?.type === "Literal") return String(key.value);
	if (key?.type === "TemplateLiteral" && key.expressions.length === 0) return key.quasis[0]?.value?.cooked ?? null;
	return null;
}
function unwrapTs(node) {
	while (node && (node.type === "TSAsExpression" || node.type === "TSNonNullExpression" || node.type === "TSSatisfiesExpression" || isContainer(node))) node = node.expression;
	return node;
}
function resolveObject(node, context, path) {
	node = unwrapTs(node);
	if (node?.type === "ObjectExpression") return node;
	if (node?.type !== "Identifier") return null;
	const resolved = resolveIdentifier(node, context, path);
	const init = resolved && unwrapTs(resolved.init);
	return init?.type === "ObjectExpression" ? init : null;
}
function resolveMemberObject(node, context, path) {
	node = unwrapTs(node);
	if (node?.type === "Identifier") {
		const variable = variableOf(node, context);
		if (variable && isEscaped(variable)) return null;
	}
	return resolveObject(node, context, path);
}
function objectEntries(object, context, path, depth = 0) {
	const entries = [];
	for (const prop of object.properties) {
		if (prop.type === "SpreadElement") {
			const arg = unwrapTs(prop.argument);
			const inner = depth < 4 ? resolveObject(arg, context, path) : null;
			if (!inner) {
				entries.push({ unknown: prop });
				continue;
			}
			const variable = arg?.type === "Identifier" ? resolveIdentifier(arg, context, path)?.variable : null;
			if (variable) path.add(variable);
			entries.push(...objectEntries(inner, context, path, depth + 1));
			if (variable) path.delete(variable);
			continue;
		}
		if (prop.type !== "Property") {
			entries.push({ unknown: prop });
			continue;
		}
		const key = keyName$1(prop);
		if (key === null) entries.push({ unknown: prop });
		else entries.push({
			key,
			value: prop.value
		});
	}
	return entries;
}
function resolveProperty(object, key, context, path) {
	let value = void 0;
	let uncertain = false;
	for (const entry of objectEntries(object, context, path)) if ("unknown" in entry) uncertain = true;
	else if (entry.key === key) {
		value = entry.value;
		uncertain = false;
	}
	return {
		value,
		uncertain
	};
}
function resolveMemberValue(node, context, path) {
	const key = keyName$1({
		key: node.property,
		computed: node.computed
	});
	const object = key === null ? null : resolveMemberObject(node.object, context, path);
	const found = object ? resolveProperty(object, key, context, path) : {
		value: void 0,
		uncertain: true
	};
	if (found.value === void 0 || found.uncertain) return {
		key,
		unresolved: node
	};
	const variable = node.object?.type === "Identifier" ? resolveIdentifier(node.object, context, path)?.variable : null;
	return {
		key,
		value: found.value,
		variable
	};
}
function collectClassStrings(expression, context, options = {}) {
	const helpers = options.mergeFunctions ?? new Set(DEFAULT_MERGE_FUNCTIONS);
	const valueHelpers = options.variantFunctions ?? new Set(DEFAULT_VARIANT_FUNCTIONS);
	const resolve = options.resolve ?? true;
	const contextualStrings = [];
	const vocabularyStrings = [];
	const unresolved = [];
	const path = /* @__PURE__ */ new Set();
	let resolvedCalls = 0;
	const push = (value, node) => {
		const string = {
			value,
			node
		};
		contextualStrings.push(string);
		if (resolvedCalls === 0) vocabularyStrings.push(string);
	};
	const visitThrough = (node, steps, valuesMode) => {
		if (!steps.length) {
			visit(node, valuesMode);
			return;
		}
		const value = unwrapTs(node);
		switch (value?.type) {
			case "ConditionalExpression":
				visitThrough(value.consequent, steps, valuesMode);
				visitThrough(value.alternate, steps, valuesMode);
				return;
			case "LogicalExpression":
				if (value.operator !== "&&") visitThrough(value.left, steps, valuesMode);
				visitThrough(value.right, steps, valuesMode);
				return;
			case "Identifier": {
				const resolved = resolve ? resolveIdentifier(value, context, path) : null;
				if (!resolved) {
					unresolved.push(value);
					return;
				}
				path.add(resolved.variable);
				visitThrough(resolved.init, [...resolved.steps, ...steps], valuesMode);
				path.delete(resolved.variable);
				return;
			}
			case "ArrayExpression":
			case "ObjectExpression": {
				const projected = projectStatic(value, steps);
				if (projected.steps.length === steps.length) {
					unresolved.push(value);
					return;
				}
				visitThrough(projected.init, projected.steps, valuesMode);
				return;
			}
			default: unresolved.push(node);
		}
	};
	const visit = (node, valuesMode) => {
		if (!node) return;
		const forwarded = resolve ? forwardedValuesOf(node, context, "className", path) : null;
		if (forwarded) {
			if (path.has(forwarded.variable)) return;
			path.add(forwarded.variable);
			for (const alternative of forwarded.alternatives) if ("unresolved" in alternative) unresolved.push(alternative.unresolved);
			else visit(alternative.value, valuesMode);
			path.delete(forwarded.variable);
			return;
		}
		switch (node.type) {
			case "Literal":
			case "SvelteLiteral":
			case "VLiteral":
				if (typeof node.value === "string") push(node.value, node);
				return;
			case "TemplateLiteral":
				node.quasis.forEach((quasi, i) => {
					let text = quasi.value?.cooked ?? "";
					if (i > 0 && !/^\s/.test(text)) text = text.replace(/^\S+/, "");
					if (i < node.expressions.length && !/\s$/.test(text)) text = text.replace(/\S+$/, "");
					if (text.trim()) push(text, quasi);
				});
				node.expressions.forEach((expr, i) => {
					const before = node.quasis[i]?.value?.cooked ?? "";
					const after = node.quasis[i + 1]?.value?.cooked ?? "";
					if (before !== "" && !/\s$/.test(before) || after !== "" && !/^\s/.test(after)) {
						if (!unresolved.includes(node)) unresolved.push(node);
					} else visit(expr, valuesMode);
				});
				return;
			case "ConditionalExpression":
				visit(node.consequent, valuesMode);
				visit(node.alternate, valuesMode);
				return;
			case "LogicalExpression":
				if (node.operator !== "&&") visit(node.left, valuesMode);
				visit(node.right, valuesMode);
				return;
			case "ArrayExpression":
				for (const el of node.elements) visit(el, valuesMode);
				return;
			case "NewExpression":
				if (node.callee?.type === "Identifier" && node.callee.name === "Set") {
					for (const arg of node.arguments) visit(arg, valuesMode);
					return;
				}
				unresolved.push(node);
				return;
			case "ObjectExpression":
				for (const entry of objectEntries(node, context, path)) if ("unknown" in entry) unresolved.push(entry.unknown);
				else if (valuesMode) visit(entry.value, valuesMode);
				else push(entry.key, keyNodeOf(node, entry));
				return;
			case "CallExpression": {
				const callee = node.callee?.type === "Identifier" ? node.callee.name : null;
				if (callee && helpers.has(callee)) {
					const hopped = path.size > 0;
					if (!hopped && node !== expression) options.onHelperCall?.(node);
					if (hopped) resolvedCalls++;
					if (valueHelpers.has(callee)) for (const arg of node.arguments) visitVariantConfig(arg);
					else for (const arg of node.arguments) visit(arg, false);
					if (hopped) resolvedCalls--;
					return;
				}
				unresolved.push(node);
				return;
			}
			case "Identifier": {
				if (node.name === "undefined") return;
				const resolved = resolve ? resolveIdentifier(node, context, path) : null;
				if (!resolved) {
					unresolved.push(node);
					return;
				}
				path.add(resolved.variable);
				visitThrough(resolved.init, resolved.steps, valuesMode);
				path.delete(resolved.variable);
				return;
			}
			case "MemberExpression": {
				const found = resolveMemberValue(node, context, path);
				if (!found.key || "unresolved" in found) {
					unresolved.push(node);
					return;
				}
				if (found.variable) path.add(found.variable);
				visit(found.value, valuesMode);
				if (found.variable) path.delete(found.variable);
				return;
			}
			case "JSXExpressionContainer":
			case "SvelteMustacheTag":
			case "VExpressionContainer":
				visit(node.expression, valuesMode);
				return;
			case "TSAsExpression":
			case "TSNonNullExpression":
			case "TSSatisfiesExpression":
				visit(node.expression, valuesMode);
				return;
			default: unresolved.push(node);
		}
	};
	const visitVariantConfig = (node) => {
		if (!node) return;
		if (node.type !== "ObjectExpression") {
			visit(node, true);
			return;
		}
		for (const prop of node.properties) {
			if (prop.type !== "Property") {
				unresolved.push(prop);
				continue;
			}
			switch (keyName$1(prop)) {
				case "base":
				case "slots":
				case "class":
				case "className":
				case "variants":
					visit(prop.value, true);
					break;
				case "compoundVariants":
				case "compoundSlots": if (prop.value?.type === "ArrayExpression") for (const entry of prop.value.elements) {
					if (entry?.type !== "ObjectExpression") continue;
					for (const inner of entry.properties) {
						if (inner.type !== "Property") continue;
						const innerKey = keyName$1(inner);
						if (innerKey === "class" || innerKey === "className") visit(inner.value, true);
					}
				}
			}
		}
	};
	visit(expression, options.valuesMode ?? false);
	return {
		contextualStrings,
		vocabularyStrings,
		unresolved
	};
}
function keyNodeOf(object, entry) {
	for (const prop of object.properties) if (prop.type === "Property" && prop.value === entry.value) return prop.key;
	return object;
}
function collectFromValue(value, context, options = {}) {
	if (!value) return {
		contextualStrings: [],
		vocabularyStrings: [],
		unresolved: []
	};
	const object = resolveObject(value, context, /* @__PURE__ */ new Set());
	if (object) return collectClassStrings(object, context, {
		...options,
		valuesMode: true
	});
	return collectClassStrings(value, context, options);
}
const sharedByProgram = /* @__PURE__ */ new WeakMap();
const NO_VISITORS = {};
function escapeRegExp(value) {
	return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
const helperSets = /* @__PURE__ */ new Map();
function helpersFor(key, options) {
	let sets = helperSets.get(key);
	if (sets) return sets;
	const helpers = /* @__PURE__ */ new Set([
		...DEFAULT_MERGE_FUNCTIONS,
		...options.mergeFunctions ?? [],
		...options.variantFunctions ?? []
	]);
	sets = {
		helpers,
		variantFunctions: /* @__PURE__ */ new Set([...DEFAULT_VARIANT_FUNCTIONS, ...options.variantFunctions ?? []]),
		helperCall: new RegExp(`\\b(?:${[...helpers].map(escapeRegExp).join("|")})\\s*\\(`)
	};
	helperSets.set(key, sets);
	return sets;
}
const optionKeys = /* @__PURE__ */ new WeakMap();
function keyOf(options) {
	let key = optionKeys.get(options);
	if (key === void 0) {
		key = JSON.stringify([
			options.componentImports ?? [],
			options.ignoreImports ?? [],
			options.mergeFunctions ?? [],
			options.variantFunctions ?? []
		]);
		optionKeys.set(options, key);
	}
	return key;
}
function sharedFor(context, options) {
	const program = context.sourceCode?.ast ?? context.sourceCode ?? context;
	let byKey = sharedByProgram.get(program);
	if (!byKey) {
		byKey = /* @__PURE__ */ new Map();
		sharedByProgram.set(program, byKey);
	}
	const key = keyOf(options);
	let shared = byKey.get(key);
	if (shared) return shared;
	const { helpers, variantFunctions, helperCall } = helpersFor(key, options);
	const text = context.sourceCode?.text;
	const consumedCalls = /* @__PURE__ */ new WeakSet();
	shared = {
		helpers,
		collectOptions: {
			mergeFunctions: helpers,
			variantFunctions,
			onHelperCall: (node) => consumedCalls.add(node)
		},
		imports: /* @__PURE__ */ new WeakSet(),
		consumedCalls,
		sites: /* @__PURE__ */ new WeakMap(),
		hasSites: typeof text !== "string" || /class/i.test(text) || helperCall.test(text)
	};
	byKey.set(key, shared);
	return shared;
}
function classSiteVisitors(context, options, onSite) {
	const shared = sharedFor(context, options);
	if (!shared.hasSites && !options.scanAllStrings) return NO_VISITORS;
	const tracker = shared.tracker ??= createComponentTracker(context, options);
	const reader = readerFor(context);
	const { helpers, collectOptions, consumedCalls, sites } = shared;
	const reportedStrings = /* @__PURE__ */ new WeakSet();
	const claimedVocabulary = /* @__PURE__ */ new WeakSet();
	const emit = (site) => {
		for (const string of site.contextualStrings) reportedStrings.add(string.node);
		const vocabularyStrings = site.vocabularyStrings.filter((string) => {
			if (claimedVocabulary.has(string.node)) return false;
			claimedVocabulary.add(string.node);
			return true;
		});
		onSite(vocabularyStrings.length === site.vocabularyStrings.length ? site : {
			...site,
			vocabularyStrings
		});
	};
	const resolvedOf = (element) => {
		if (!element) return null;
		const rendered = reader.renderedElementOf?.(element);
		if (!rendered) return tracker.resolveName(reader.nameOf(element));
		const resolved = tracker.resolveName(reader.nameOf(rendered));
		if (!resolved) return null;
		return {
			...resolved,
			wrapper: resolved.wrapper ?? reader.nameOf(element)?.text ?? ""
		};
	};
	const enclosingOf = (element, accepts) => {
		let direct = true;
		for (let node = reader.parentElementOf(element); node; node = reader.parentElementOf(node)) {
			const name = reader.nameOf(node);
			const resolved = tracker.resolveName(name);
			if (resolved && accepts(resolved.component)) return {
				name: name?.text ?? "",
				direct
			};
			direct = false;
		}
		return null;
	};
	const closedParentOf = (element, accepts) => {
		const parent = reader.parentElementOf(element);
		if (!parent) return null;
		const name = reader.nameOf(parent);
		const resolved = tracker.resolveName(name);
		return resolved && !accepts(resolved.component) ? name?.text ?? "" : null;
	};
	const siteFor = (node, value, attribute, resolved, element = null) => {
		const keyed = reader.classObjects === true && attribute === "class";
		return {
			...value && !keyed ? collectFromValue(value, context, collectOptions) : collectClassStrings(value ?? node, context, collectOptions),
			component: resolved?.component ?? null,
			componentFile: resolved?.file ?? null,
			wrapper: resolved?.wrapper ?? null,
			attribute,
			node,
			enclosingContainer: (accepts) => element ? enclosingOf(element, accepts) : null,
			closedParent: (accepts) => element ? closedParentOf(element, accepts) : null
		};
	};
	const attributeSites = (node) => {
		let list = sites.get(node);
		if (list) return list;
		const element = reader.elementOf(node);
		list = [siteFor(node, reader.attributeValue(node), reader.attributeName(node), resolvedOf(element), element)];
		sites.set(node, list);
		return list;
	};
	const spreadSites = (node) => {
		let list = sites.get(node);
		if (list) return list;
		list = [];
		const object = resolveObject(reader.spreadArgument(node), context, /* @__PURE__ */ new Set());
		if (object) {
			const element = reader.elementOf(node);
			const resolved = resolvedOf(element);
			const finals = /* @__PURE__ */ new Map();
			for (const entry of objectEntries(object, context, /* @__PURE__ */ new Set())) if ("key" in entry && isClassAttribute(entry.key)) finals.set(entry.key, entry.value);
			for (const [key, value] of finals) list.push(siteFor(value, value, key, resolved, element));
		}
		sites.set(node, list);
		return list;
	};
	const callSites = (node) => {
		let list = sites.get(node);
		if (list) return list;
		list = [siteFor(node, null, null, null)];
		sites.set(node, list);
		return list;
	};
	const visitors = {};
	for (const type of reader.attributes) addVisitor(visitors, type, (node) => {
		if (!isClassAttribute(reader.attributeName(node))) return;
		for (const site of attributeSites(node)) emit(site);
	});
	for (const type of reader.spreads) addVisitor(visitors, type, (node) => {
		if (!reader.spreadArgument(node)) return;
		for (const site of spreadSites(node)) emit(site);
	});
	for (const [type, read] of Object.entries(reader.extraSites ?? {})) addVisitor(visitors, type, (node) => {
		let list = sites.get(node);
		if (!list) {
			const extra = read(node);
			list = [];
			if (extra) {
				const element = reader.elementOf(extra.anchor);
				list.push({
					...siteFor(node, null, "class", resolvedOf(element), element),
					contextualStrings: extra.names,
					vocabularyStrings: extra.names,
					unresolved: []
				});
			}
			sites.set(node, list);
		}
		for (const site of list) emit(site);
	});
	return {
		ImportDeclaration(node) {
			if (shared.imports.has(node)) return;
			shared.imports.add(node);
			tracker.collectImport(node);
		},
		...visitors,
		CallExpression(node) {
			if (consumedCalls.has(node)) return;
			const callee = node.callee?.type === "Identifier" ? node.callee.name : null;
			if (!callee || !helpers.has(callee)) return;
			for (const site of callSites(node)) emit(site);
		},
		...options.scanAllStrings ? { Literal(node) {
			if (typeof node.value !== "string" || !node.value.includes("-")) return;
			if (reportedStrings.has(node) || claimedVocabulary.has(node)) return;
			if (node.parent?.type === "ImportDeclaration") return;
			const strings = [{
				value: node.value,
				node
			}];
			emit({
				contextualStrings: strings,
				vocabularyStrings: strings,
				unresolved: [],
				component: null,
				componentFile: null,
				wrapper: null,
				attribute: null,
				node,
				enclosingContainer: () => null,
				closedParent: () => null
			});
		} } : {}
	};
}

//#endregion
//#region src/rules/contracts.ts
function globToRegExp(glob) {
	const escaped = glob.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, "[^\\s]+");
	return new RegExp(`^${escaped}$`);
}
function compileEntries(entries, groupIds, classifier) {
	const set = {
		source: entries ?? [],
		categories: /* @__PURE__ */ new Set(),
		layout: false,
		groups: /* @__PURE__ */ new Set(),
		basePatterns: [],
		fullPatterns: []
	};
	for (const raw of entries ?? []) if (raw === "layout") set.layout = true;
	else if (CATEGORIES.includes(raw)) set.categories.add(raw);
	else if (raw.includes(":")) set.fullPatterns.push(globToRegExp(raw));
	else {
		const entry = stripModifier(normalizeClass(raw), classifier);
		if (groupIds.has(entry)) set.groups.add(entry);
		if (!groupIds.has(entry) || classifier.groupOf(entry)) set.basePatterns.push(globToRegExp(entry));
	}
	return set;
}
function stripModifier(base, classifier) {
	if (/-\d+\/\d+$/.test(base) && categoryOf(classifier.groupOf(base)) !== "color") return base;
	return base.replace(/\/[\w.%]+$/, "");
}
function matches(set, token, classifier) {
	if (!set.source.length) return false;
	const group = classifier.groupOf(token);
	if (group && set.groups.has(group)) return true;
	const category = categoryOf(group);
	if (category && set.categories.has(category)) return true;
	if (!category && set.layout && (group || isMarkerClass(token))) return true;
	const base = stripModifier(normalizeClass(token), classifier);
	if (set.basePatterns.some((re) => re.test(base))) return true;
	if (set.fullPatterns.some((re) => re.test(token))) return true;
	return false;
}
const groupIdsByConfig = /* @__PURE__ */ new WeakMap();
function groupIdsFor(config) {
	let ids = groupIdsByConfig.get(config);
	if (!ids) {
		ids = new Set(Object.keys(config.classGroups));
		groupIdsByConfig.set(config, ids);
	}
	return ids;
}
const compiledByConfig = /* @__PURE__ */ new WeakMap();
function compiledOnce(fromFile, key, build) {
	const config = resolveCnConfig(fromFile);
	let byKey = compiledByConfig.get(config);
	if (!byKey) {
		byKey = /* @__PURE__ */ new Map();
		compiledByConfig.set(config, byKey);
	}
	let value = byKey.get(key);
	if (value === void 0) {
		value = build();
		byKey.set(key, value);
	}
	return value;
}
function messageTable(message) {
	if (typeof message === "string") return { default: message };
	if (!message || typeof message !== "object") return null;
	const table = {};
	for (const [key, value] of Object.entries(message)) if (typeof value === "string") table[key] = value;
	return Object.keys(table).length ? table : null;
}
function compileContracts(inputs, options = {}) {
	const key = `contracts:${JSON.stringify([
		options.allow ?? null,
		options.deny ?? null,
		options.message ?? null,
		options.uncheckedEntries ?? false,
		inputs ?? []
	])}`;
	return compiledOnce(options.fromFile, key, () => buildContracts(inputs, options));
}
var ContractConfigError = class extends Error {};
function configErrorVisitors(context, error) {
	if (!(error instanceof ContractConfigError)) throw error;
	const message = error.message;
	return { Program(node) {
		context.report({
			node,
			loc: {
				line: 1,
				column: 0
			},
			message
		});
	} };
}
function compilePattern(pattern) {
	try {
		return new RegExp(pattern);
	} catch (error) {
		if (!(error instanceof SyntaxError)) throw error;
		throw new ContractConfigError(`Contract pattern "${pattern}" is not a valid regular expression.`);
	}
}
function checkEntries(entries, groupIds, classifier, fromFile) {
	for (const entry of entries ?? []) {
		if (entry === "layout" || entry.includes("*") || entry.includes(":")) continue;
		if (CATEGORIES.includes(entry)) continue;
		if (groupIds.has(entry)) continue;
		if (classifier.groupOf(entry)) continue;
		const known = fromFile ? knownClassesFor(fromFile) : null;
		if (known?.utilities.has(entry) || known?.classes.has(entry)) continue;
		const hint = /^[A-Za-z][A-Za-z0-9]*$/.test(entry) ? didYouMean(entry, [
			...CATEGORIES,
			"layout",
			...groupIds
		]) : null;
		if (hint) throw new ContractConfigError(`Contract entry "${entry}" is not a category (${[...CATEGORIES, "layout"].join(", ")}), a class group, or a class, so it would match nothing. Did you mean "${hint}"?`);
		warnOnce(`contract-entry:${entry}`, `Contract entry "${entry}" is not a category (${[...CATEGORIES, "layout"].join(", ")}), a class group, or a class cn or your theme knows; it matches only a class named exactly that.`);
	}
}
function checkAllowEntries(entries, fromFile, rule) {
	if (!entries?.length) return;
	const classifier = projectClassifierFor(fromFile);
	const groupIds = groupIdsFor(resolveCnConfig(fromFile));
	for (const entry of entries) if (/^[a-z]+-\d{2,3}$/.test(entry) && !groupIds.has(entry) && !classifier.groupOf(entry)) throw new ContractConfigError(`${rule}: allow entry "${entry}" names a color, not a class, so it would match nothing. Did you mean "*-${entry}" (the color on any utility), or "bg-${entry}"?`);
	checkEntries(entries, groupIds, classifier, fromFile);
}
function compileVocabularyPolicy(options, rule) {
	if (!options.uncheckedEntries) {
		checkAllowEntries(options.allow, options.fromFile, rule);
		checkAllowEntries(options.deny, options.fromFile, rule);
		for (const c of options.contracts ?? []) {
			checkAllowEntries(c.allow, options.fromFile, rule);
			checkAllowEntries(c.deny, options.fromFile, rule);
		}
	}
	return compileContracts(options.contracts, {
		allow: options.allow,
		deny: options.deny,
		message: options.message,
		uncheckedEntries: options.uncheckedEntries,
		fromFile: options.fromFile
	});
}
function allowListOf(policy, inherited) {
	if (policy.allow !== void 0) return policy.allow;
	if (inherited !== void 0) return inherited;
	return policy.deny !== void 0 ? ["*"] : [];
}
function buildContracts(inputs, options) {
	const classifier = projectClassifierFor(options.fromFile);
	const groupIds = groupIdsFor(resolveCnConfig(options.fromFile));
	if (!options.uncheckedEntries) {
		checkEntries(options.allow, groupIds, classifier, options.fromFile);
		checkEntries(options.deny, groupIds, classifier, options.fromFile);
		for (const c of inputs ?? []) {
			checkEntries(c.allow, groupIds, classifier, options.fromFile);
			checkEntries(c.deny, groupIds, classifier, options.fromFile);
		}
	}
	const topAllow = allowListOf(options);
	const topDeny = options.deny ?? [];
	const compiled = (inputs ?? []).map((c) => {
		const pattern = compilePattern(c.pattern);
		const message = messageTable(c.message);
		for (const text of Object.values(message ?? {})) checkMessage(text, c.pattern);
		return {
			pattern,
			allow: compileEntries(allowListOf(c, topAllow), groupIds, classifier),
			deny: compileEntries(c.deny ?? topDeny, groupIds, classifier),
			message
		};
	});
	const baselineMessage = messageTable(options.message);
	for (const text of Object.values(baselineMessage ?? {})) checkMessage(text, "no-restyle");
	const baseline = {
		allow: compileEntries(topAllow, groupIds, classifier),
		deny: compileEntries(topDeny, groupIds, classifier),
		message: baselineMessage
	};
	const cache = /* @__PURE__ */ new Map();
	const verdicts = /* @__PURE__ */ new Map();
	const policyFor = (name) => {
		const cached = cache.get(name);
		if (cached) return cached;
		let policy = baseline;
		for (let i = compiled.length - 1; i >= 0; i--) if (compiled[i].pattern.test(name)) {
			policy = compiled[i];
			break;
		}
		cache.set(name, policy);
		return policy;
	};
	const decide = (component, token) => {
		const key = `${component ?? ""}\u0000${token}`;
		const known = verdicts.get(key);
		if (known) return known;
		if (verdicts.size > 5e4) verdicts.clear();
		const verdict = decideUncached(component, token);
		verdicts.set(key, verdict);
		return verdict;
	};
	const decideUncached = (component, token) => {
		const policy = component === null ? baseline : policyFor(component);
		const group = classifier.groupOf(token);
		const category = group || isMarkerClass(token) ? categoryOf(group) ?? "layout" : "unclassified";
		const words = (table) => table ? table[category] ?? table.default ?? null : null;
		const message = words(policy.message) ?? words(baseline.message);
		if (matches(policy.deny, token, classifier)) return {
			kind: "denied",
			entries: policy.deny.source,
			category,
			message
		};
		if (matches(policy.allow, token, classifier)) return { kind: "ok" };
		return {
			kind: "not-allowed",
			entries: policy.allow.source,
			category,
			message
		};
	};
	const primitivesFor = (token, except, indexed) => {
		const granting = compiled.filter((c) => matches(c.allow, token, classifier));
		if (!granting.length) return [];
		const names = /* @__PURE__ */ new Set();
		for (const c of granting) for (const n of literalNames(c.pattern)) names.add(n);
		for (const n of indexed()) names.add(n);
		const covered = new Set(except);
		const out = [];
		for (const name of names) {
			if (covered.has(name)) continue;
			if (!granting.some((c) => c.pattern.test(name))) continue;
			if (decide(name, token).kind !== "ok") continue;
			out.push(name);
			if (out.length > 4) return [];
		}
		return out;
	};
	return {
		decide,
		primitivesFor
	};
}
function literalNames(pattern) {
	const parts = pattern.source.replace(/^\^/, "").replace(/\$$/, "").replace(/^\((?:\?:)?/, "").replace(/\)$/, "").split("|");
	return parts.every((part) => /^[A-Za-z_$][\w$]*$/.test(part)) ? parts : [];
}

//#endregion
//#region src/rules/fixes.ts
function replaceInMarkup(node, context, token, replacement) {
	const raw = context.sourceCode?.getText?.(node) ?? "";
	const quote = raw[0] === "\"" || raw[0] === "'" ? raw[0] : "";
	const inner = quote ? raw.slice(1, -1) : raw;
	if (quote && raw[raw.length - 1] !== quote) return null;
	const replaced = replaceClass(inner, token, replacement);
	return replaced === inner ? null : `${quote}${replaced}${quote}`;
}
function replaceInLiteral(node, context, token, replacement) {
	if (isMarkupLiteral(node) && typeof node.value === "string") return replaceInMarkup(node, context, token, replacement);
	if (node?.type !== "Literal" || typeof node.value !== "string") return null;
	const raw = node.raw ?? context.sourceCode?.getText?.(node) ?? "";
	const quote = raw[0];
	if (quote !== "\"" && quote !== "'" || raw[raw.length - 1] !== quote) return null;
	const inner = raw.slice(1, -1);
	if (!(node.parent?.type === "JSXAttribute") && inner !== node.value) return null;
	const replaced = replaceClass(inner, token, replacement);
	return replaced === inner ? null : `${quote}${replaced}${quote}`;
}
function classSuggestion(node, context, token, replacement, messageId, data) {
	const text = replaceInLiteral(node, context, token, replacement);
	if (text === null) return null;
	return {
		messageId,
		data,
		fix: (fixer) => fixer.replaceText(node, text)
	};
}
function classSuggestions(node, context, token, replacements, messageId, key) {
	const list = replacements.map((replacement) => classSuggestion(node, context, token, replacement, messageId, { [key]: replacement })).filter((s) => s !== null);
	return list.length ? list : void 0;
}

//#endregion
//#region src/rules/policy-schema.ts
const entriesSchema = {
	type: "array",
	items: { type: "string" }
};
const message = {
	type: "string",
	maxLength: 500
};
const recognitionSchema = {
	componentImports: entriesSchema,
	ignoreImports: entriesSchema,
	mergeFunctions: entriesSchema,
	variantFunctions: entriesSchema
};
const contractsSchema = {
	type: "array",
	items: {
		type: "object",
		properties: {
			pattern: { type: "string" },
			allow: entriesSchema,
			deny: entriesSchema,
			message
		},
		required: ["pattern"],
		additionalProperties: false
	}
};
const policySchema = {
	allow: entriesSchema,
	deny: entriesSchema,
	contracts: contractsSchema,
	message
};

//#endregion
//#region src/rules/suggest.ts
const COLOR_THRESHOLD = .12;
const PRIORITY = [
	"background",
	"foreground",
	"muted",
	"muted-foreground",
	"primary",
	"primary-foreground",
	"secondary",
	"secondary-foreground",
	"accent",
	"accent-foreground",
	"destructive",
	"destructive-foreground",
	"border",
	"input",
	"ring",
	"card",
	"card-foreground",
	"popover",
	"popover-foreground"
];
const priorityOf = (name) => {
	const index = PRIORITY.indexOf(name);
	return index === -1 ? PRIORITY.length : index;
};
function roleOf(prefix) {
	return /^(?:text|placeholder|caret|decoration|fill|stroke)-$/.test(prefix) ? "text" : "surface";
}
const isForeground = (name) => name === "foreground" || name.endsWith("-foreground");
function nearestColorTokens(lab, tokens, role, limit = 2) {
	const groups = /* @__PURE__ */ new Map();
	for (const [name, value] of tokens) {
		const distance = colorDistance(lab, value);
		if (distance > .12) continue;
		const key = distance.toFixed(3);
		const group = groups.get(key);
		if (group) group.names.push(name);
		else groups.set(key, {
			distance,
			names: [name]
		});
	}
	const prefer = role === "text" ? isForeground : (n) => !isForeground(n);
	let candidates = [...groups.values()].sort((a, b) => a.distance - b.distance).map(({ names }) => names.sort((a, b) => Number(prefer(b)) - Number(prefer(a)) || priorityOf(a) - priorityOf(b) || a.localeCompare(b))[0]);
	if (role === "surface" && candidates.some((n) => !isForeground(n))) candidates = candidates.filter((n) => !isForeground(n));
	return candidates.slice(0, limit);
}
function paletteColor(value) {
	const raw = PALETTE[value];
	return raw ? parseColor(raw) : null;
}
function arbitraryColor(inner) {
	const text = inner.replace(/^color:/, "").replace(/_/g, " ");
	return parseColor(text);
}
function nearestSteps(px, scale, limit = 2) {
	return [...scale].map(([name, value]) => ({
		name,
		px: value,
		exact: Math.abs(value - px) < .01
	})).sort((a, b) => Math.abs(a.px - px) - Math.abs(b.px - px) || a.px - b.px).slice(0, limit);
}
function formatSteps(steps, toClass) {
	return steps.map((s) => `${toClass(s.name)} (${formatPx(s.px)})`).join(", ");
}

//#endregion
//#region src/rules/no-arbitrary-values.ts
const PX_SPACING = /^(-?)([a-z]+(?:-[a-z]+)*)-\[(\d+(?:\.\d+)?)px\]$/;
const SPACING_GROUPS = /* @__PURE__ */ new Set([
	"m",
	"mx",
	"my",
	"ms",
	"me",
	"mt",
	"mr",
	"mb",
	"ml",
	"w",
	"min-w",
	"max-w",
	"h",
	"min-h",
	"max-h",
	"size",
	"inset",
	"inset-x",
	"inset-y",
	"start",
	"end",
	"top",
	"right",
	"bottom",
	"left",
	"translate",
	"translate-x",
	"translate-y",
	"basis",
	"indent",
	"leading",
	"scroll-m",
	"scroll-mx",
	"scroll-my",
	"scroll-mt",
	"scroll-mr",
	"scroll-mb",
	"scroll-ml",
	"scroll-p",
	"scroll-px",
	"scroll-py",
	"scroll-pt",
	"scroll-pr",
	"scroll-pb",
	"scroll-pl"
]);
function splitArbitrary(token) {
	const match = normalizeClass(token).match(/^(.+?)-\[([^\]]*)\](.*)$/);
	return match ? {
		utility: match[1],
		inner: match[2],
		suffix: match[3]
	} : null;
}
function scaleEquivalent(token, unitPx = 4) {
	if (unitPx === null) return null;
	const { variants, base } = splitVariants(token);
	const leading = base.startsWith("!") ? "!" : "";
	const trailing = !leading && base.endsWith("!") ? "!" : "";
	const match = base.slice(leading.length, base.length - trailing.length).match(PX_SPACING);
	if (!match) return null;
	const [, negative, utility, px] = match;
	const steps = Number(px) / unitPx;
	if (!Number.isInteger(steps * 4)) return null;
	return `${variants.length ? `${variants.join(":")}:` : ""}${leading}${negative}${utility}-${steps}${trailing}`;
}
const MESSAGES$5 = {
	arbitraryValue: "\"{{className}}\" hardcodes an off-token value. Use a theme token or scale value instead.",
	arbitraryValueWithScale: "\"{{className}}\" hardcodes an off-token value. Use \"{{replacement}}\" instead (same value, on the scale).",
	arbitraryValueNearScale: "\"{{className}}\" hardcodes an off-token value. Nearest on the scale: {{suggestions}}.",
	arbitraryColorNear: "\"{{className}}\" hardcodes a color. Nearest theme tokens: {{suggestions}}. Use one of those, or declare --color-<name> in {{file}}.",
	arbitraryColorFar: "\"{{className}}\" hardcodes a color and no declared theme color is close to it. Use one of: {{tokens}}, or declare --color-<name> in {{file}}.",
	useScale: "Replace with \"{{replacement}}\" (same value, on the scale).",
	useToken: "Replace with \"{{replacement}}\"."
};
const noArbitraryValues = {
	meta: {
		type: "problem",
		hasSuggestions: true,
		docs: {
			description: "Disallow arbitrary values on appearance utilities; use theme tokens and scale values.",
			url: "https://github.com/shadcn-ui/lint/blob/main/docs/rules/no-arbitrary-values.md"
		},
		schema: [{
			type: "object",
			properties: {
				...policySchema,
				scanAllStrings: { type: "boolean" },
				...recognitionSchema
			},
			additionalProperties: false
		}],
		messages: MESSAGES$5
	},
	create(context) {
		const options = withSettings(context, context.options?.[0] ?? {});
		const emit = reporter(context, MESSAGES$5, {
			rule: "shadcn/no-arbitrary-values",
			message: options.message
		});
		const filename = fileOf(context);
		let policy;
		try {
			policy = compileVocabularyPolicy({
				...options,
				fromFile: filename
			}, "shadcn/no-arbitrary-values");
		} catch (error) {
			return configErrorVisitors(context, error);
		}
		const { groupOf } = projectClassifierFor(filename);
		let file;
		let unitPx;
		const colorSuggestions = (token, parts) => {
			const lab = arbitraryColor(parts.inner);
			const colors = lab ? colorValuesFor(filename) : null;
			if (!lab || !colors?.size) return null;
			return nearestColorTokens(lab, colors, roleOf(`${parts.utility}-`)).map((name) => withBase(token, `${parts.utility}-${name}${parts.suffix}`));
		};
		return classSiteVisitors(context, options, (site) => {
			for (const { value, node } of site.vocabularyStrings) for (const token of splitClasses(value)) {
				if (!isArbitraryValue$1(token)) continue;
				const exemption = policy.decide(site.component, token);
				if (exemption.kind === "ok") continue;
				if (file === void 0) {
					const themeFile = themeFileFor(filename);
					file = themeFile ? displayPath(themeFile, context) : "your theme CSS";
				}
				const group = groupOf(token);
				const category = categoryOf(group);
				const parts = splitArbitrary(token);
				if (category === "color" && parts) {
					const suggestions = colorSuggestions(token, parts);
					if (suggestions) {
						emit({
							node,
							messageId: suggestions.length ? "arbitraryColorNear" : "arbitraryColorFar",
							data: {
								className: token,
								component: site.component ?? "",
								suggestions: suggestions.join(", "),
								tokens: listTokens(colorTokensFor(filename) ?? /* @__PURE__ */ new Set()),
								file
							},
							suggest: classSuggestions(node, context, token, suggestions, "useToken", "replacement")
						}, exemption.message);
						continue;
					}
				}
				let replacement = null;
				let near = null;
				const scaleKind = group === "font-size" ? "text" : group && /^rounded(-|$)/.test(group) ? "radius" : null;
				if (category === "spacing" || group && SPACING_GROUPS.has(group)) {
					if (unitPx === void 0) unitPx = spacingBaseFor(filename);
					replacement = scaleEquivalent(token, unitPx);
				} else if (scaleKind && parts) {
					const px = lengthInPx(parts.inner.replace(/_/g, " "));
					const steps = px === null ? [] : nearestSteps(px, scaleFor(filename, scaleKind));
					const toClass = (name) => withBase(token, `${parts.utility}-${name}${parts.suffix}`);
					if (steps[0]?.exact) replacement = toClass(steps[0].name);
					else if (steps.length) near = formatSteps(steps, toClass);
				}
				emit({
					node,
					messageId: replacement ? "arbitraryValueWithScale" : near ? "arbitraryValueNearScale" : "arbitraryValue",
					data: {
						className: token,
						component: site.component ?? "",
						replacement: replacement ?? "",
						suggestions: near ?? "",
						file
					},
					suggest: replacement ? classSuggestions(node, context, token, [replacement], "useScale", "replacement") : void 0
				}, exemption.message);
			}
		});
	}
};

//#endregion
//#region src/rules/no-inline-styles.ts
const COLOR_FUNCTION$1 = /#[0-9a-f]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|hwb|oklch|oklab|lab|lch|color|color-mix|light-dark)\(/i;
function colorValueText(value) {
	let text = "";
	let quote = "";
	let urlDepth = 0;
	for (let i = 0; i < value.length; i++) {
		const char = value[i];
		if (quote) {
			if (char === "\\") i++;
			else if (char === quote) quote = "";
			continue;
		}
		if (char === "/" && value[i + 1] === "*") {
			const end = value.indexOf("*/", i + 2);
			i = end === -1 ? value.length : end + 1;
			text += " ";
			continue;
		}
		if (char === "\"" || char === "'") {
			quote = char;
			text += " ";
			continue;
		}
		if (char === "\\") {
			if (!urlDepth) text += value.slice(i, i + 2);
			i++;
			continue;
		}
		if (urlDepth) {
			if (char === "(") urlDepth++;
			else if (char === ")") urlDepth--;
			continue;
		}
		if (value.slice(i, i + 4).toLowerCase() === "url(" && (i === 0 || !/[\w-]/.test(value[i - 1]))) {
			urlDepth = 1;
			i += 3;
			text += " ";
			continue;
		}
		text += char;
	}
	return text;
}
function hasRawColor(value) {
	const text = colorValueText(value);
	if (COLOR_FUNCTION$1.test(text) || parseColor(text) !== null) return true;
	return text.replace(/var\([^)]*\)/gi, " ").split(/[\s,()/]+/).some((leaf) => leaf && parseColor(leaf) !== null);
}
function unwrap(node) {
	while (node && (node.type === "TSAsExpression" || node.type === "TSSatisfiesExpression" || node.type === "TSNonNullExpression")) node = node.expression;
	return node;
}
function cssPropertyName(name) {
	if (name.startsWith("--")) return name;
	return name.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`).toLowerCase();
}
function propertyMatcher(entries) {
	const patterns = (entries ?? []).map((entry) => {
		if (!/^--[\w*-]+$/.test(entry) && !/^[a-zA-Z*][a-zA-Z*-]*$/.test(entry)) throw new ContractConfigError(`shadcn/no-inline-styles: entry "${entry}" is not a CSS property name (backgroundColor, background-color, border-*, --chart-1), so it would match nothing.`);
		return new RegExp(`^${cssPropertyName(entry).replace(/\*/g, ".*")}$`);
	});
	return (property) => {
		const name = cssPropertyName(property);
		return patterns.some((pattern) => pattern.test(name));
	};
}
function compilePropertyPolicy(options) {
	const topAllow = allowListOf(options);
	const topDeny = options.deny ?? [];
	const compile = (policy, inherited) => ({
		allow: propertyMatcher(allowListOf(policy, inherited?.allow)),
		deny: propertyMatcher(policy.deny ?? inherited?.deny),
		message: (inherited ? policy.message : void 0) ?? null
	});
	const baseline = compile(options);
	const contracts = (options.contracts ?? []).map((c) => {
		let pattern;
		try {
			pattern = new RegExp(c.pattern);
		} catch {
			throw new ContractConfigError(`Contract pattern "${c.pattern}" is not a valid regular expression.`);
		}
		return {
			pattern,
			...compile(c, {
				allow: topAllow,
				deny: topDeny
			})
		};
	});
	const policyFor = (component) => {
		for (let i = contracts.length - 1; i >= 0; i--) if (contracts[i].pattern.test(component)) return contracts[i];
		return baseline;
	};
	const decide = (component, property) => {
		const policy = component ? policyFor(component) : baseline;
		if (policy.deny(property)) return {
			exempt: false,
			message: policy.message
		};
		if (policy.allow(property)) return {
			exempt: true,
			message: null
		};
		return {
			exempt: false,
			message: policy.message
		};
	};
	const wordsFor = (component) => component ? policyFor(component).message : null;
	return {
		decide,
		wordsFor
	};
}
function carriesRawColor(node, context, seen = /* @__PURE__ */ new Set()) {
	node = unwrap(node);
	if (!node) return false;
	switch (node.type) {
		case "Literal": return typeof node.value === "string" && hasRawColor(node.value);
		case "TemplateLiteral": return hasRawColor(node.quasis.map((q) => q.value?.cooked ?? "").join("￼"));
		case "ConditionalExpression": return carriesRawColor(node.consequent, context, seen) || carriesRawColor(node.alternate, context, seen);
		case "LogicalExpression": return carriesRawColor(node.left, context, seen) || carriesRawColor(node.right, context, seen);
		case "ObjectExpression": return node.properties.some((p) => p.type === "Property" && carriesRawColor(p.value, context, seen));
		case "ArrayExpression": return node.elements.some((el) => carriesRawColor(el, context, seen));
		case "Identifier": {
			const init = resolveIdentifier(node, context, seen)?.init;
			return init ? carriesRawColor(init, context, seen) : false;
		}
		case "MemberExpression":
			if (node.object?.type === "Identifier") {
				const init = resolveIdentifier(node.object, context, seen)?.init;
				return init ? carriesRawColor(init, context, seen) : false;
			}
			return carriesRawColor(node.object, context, seen);
		default: return false;
	}
}
function splitDeclarations(css) {
	const out = [];
	let start = 0;
	let depth = 0;
	let quote = "";
	for (let i = 0; i < css.length; i++) {
		const char = css[i];
		if (quote) {
			if (char === "\\") i++;
			else if (char === quote) quote = "";
		} else if (char === "\"" || char === "'") quote = char;
		else if (char === "(") depth++;
		else if (char === ")") depth = Math.max(0, depth - 1);
		else if (char === ";" && depth === 0) {
			out.push(css.slice(start, i));
			start = i + 1;
		}
	}
	out.push(css.slice(start));
	return out;
}
function cssTextOf(node) {
	if ((node?.type === "Literal" || isMarkupLiteral(node)) && typeof node.value === "string") return node.value;
	if (node?.type === "TemplateLiteral") return node.quasis.map((q) => q.value?.cooked ?? "").join("￼");
	return null;
}
const MESSAGES$4 = {
	inlineStyle: "Inline style sets {{property}}. Style through classes; use CSS custom properties for dynamic values.",
	dynamicStyle: "Dynamic style object cannot be checked. Build it from CSS custom properties only.",
	customPropColor: "Custom property {{property}} hardcodes a color. Define it as a theme token instead of injecting a raw value.",
	styleElement: "A <style> element injects CSS outside the design system. Use classes, or declare the rule in your theme CSS."
};
const noInlineStyles = {
	meta: {
		type: "problem",
		docs: {
			description: "Disallow inline style attributes, except CSS custom properties.",
			url: "https://github.com/shadcn-ui/lint/blob/main/docs/rules/no-inline-styles.md"
		},
		schema: [{
			type: "object",
			properties: policySchema,
			additionalProperties: false
		}],
		messages: MESSAGES$4
	},
	create(context) {
		const options = context.options?.[0] ?? {};
		const emit = reporter(context, MESSAGES$4, {
			rule: "shadcn/no-inline-styles",
			message: options.message
		});
		let policy;
		try {
			policy = compilePropertyPolicy(options);
		} catch (error) {
			return configErrorVisitors(context, error);
		}
		const reader = readerFor(context);
		const elementName = (attribute) => {
			const name = reader.nameOf(reader.elementOf(attribute));
			return name?.component ? name.text : "";
		};
		const judge = (key, value, component, text) => {
			const verdict = policy.decide(component, key);
			if (verdict.exempt) return;
			const messageId = !key.startsWith("--") ? "inlineStyle" : (text === void 0 ? carriesRawColor(value, context) : hasRawColor(text)) ? "customPropColor" : null;
			if (!messageId) return;
			emit({
				node: value,
				messageId,
				data: {
					property: key,
					component
				}
			}, verdict.message);
		};
		const judgeDeclarations = (css, reportAt, component) => {
			for (const declaration of splitDeclarations(css)) {
				const colon = declaration.indexOf(":");
				if (colon === -1) continue;
				const property = declaration.slice(0, colon).trim();
				if (!property) continue;
				judge(property, reportAt, component, declaration.slice(colon + 1));
			}
		};
		const check = (expr, reportAt, seen = /* @__PURE__ */ new Set(), component = "") => {
			expr = unwrap(expr);
			if (!expr) return;
			const forwarded = forwardedValuesOf(expr, context, "style", seen);
			if (forwarded && !seen.has(forwarded.variable)) {
				seen.add(forwarded.variable);
				for (const alternative of forwarded.alternatives) if ("unresolved" in alternative) emit({
					node: reportAt,
					messageId: "dynamicStyle",
					data: { component }
				}, policy.wordsFor(component));
				else check(alternative.value, reportAt, seen, component);
				seen.delete(forwarded.variable);
				return;
			}
			if (expr.type === "Identifier" && expr.name === "undefined" || expr.type === "Literal" && expr.value === null) return;
			if (reader.staticStyles) {
				const css = cssTextOf(expr);
				if (css !== null) return judgeDeclarations(css, reportAt, component);
			}
			if (expr.type === "ConditionalExpression") {
				check(expr.consequent, expr.consequent, seen, component);
				check(expr.alternate, expr.alternate, seen, component);
				return;
			}
			if (expr.type === "LogicalExpression") {
				if (expr.operator !== "&&") check(expr.left, expr.left, seen, component);
				check(expr.right, expr.right, seen, component);
				return;
			}
			if (expr.type === "Identifier") {
				const init = resolveIdentifier(expr, context, seen)?.init;
				if (init) return check(init, reportAt, seen, component);
				emit({
					node: reportAt,
					messageId: "dynamicStyle",
					data: { component }
				}, policy.wordsFor(component));
				return;
			}
			if (expr.type === "MemberExpression") {
				const found = resolveMemberValue(expr, context, seen);
				if (!("unresolved" in found) && found.value) return check(found.value, reportAt, seen, component);
			}
			if (expr.type !== "ObjectExpression") {
				emit({
					node: reportAt,
					messageId: "dynamicStyle",
					data: { component }
				}, policy.wordsFor(component));
				return;
			}
			const properties = /* @__PURE__ */ new Map();
			for (const entry of objectEntries(expr, context, seen)) {
				if ("unknown" in entry) {
					const prop = entry.unknown;
					if (prop.type === "SpreadElement" && isForwardedProp(unwrap(prop.argument), context, "style")) {
						check(prop.argument, prop, seen, component);
						continue;
					}
					emit({
						node: prop,
						messageId: "dynamicStyle",
						data: { component }
					}, policy.wordsFor(component));
					continue;
				}
				properties.set(entry.key, entry.value);
			}
			for (const [key, value] of properties) judge(key, value, component);
		};
		const visitors = { JSXOpeningElement(node) {
			if (node.name?.type === "JSXIdentifier" && node.name.name === "style") emit({
				node,
				messageId: "styleElement"
			});
		} };
		for (const type of reader.attributes) addVisitor(visitors, type, (node) => {
			if (reader.attributeName(node) !== "style") return;
			const value = reader.attributeValue(node);
			if (isContainer(value)) check(value.expression, value.expression, /* @__PURE__ */ new Set(), elementName(node));
			else if (reader.staticStyles && value) check(value, value, /* @__PURE__ */ new Set(), elementName(node));
		});
		for (const [type, read] of Object.entries(reader.styleProperties ?? {})) visitors[type] = (node) => {
			const style = read(node);
			if (!style) return;
			const value = isContainer(style.value) ? style.value.expression : style.value;
			const text = cssTextOf(value);
			judge(style.property, text === null ? value : node, elementName(node), text ?? void 0);
		};
		for (const type of reader.spreads) addVisitor(visitors, type, (node) => {
			const object = resolveObject(reader.spreadArgument(node), context, /* @__PURE__ */ new Set());
			if (!object) return;
			const { value, uncertain } = resolveProperty(object, "style", context, /* @__PURE__ */ new Set());
			if (!value) return;
			const component = elementName(node);
			if (uncertain) emit({
				node,
				messageId: "dynamicStyle",
				data: { component }
			}, policy.wordsFor(component));
			else check(value, value, /* @__PURE__ */ new Set(), component);
		});
		return visitors;
	}
};

//#endregion
//#region src/tailwind/client.ts
let bridge = null;
let restarts = 0;
const FIRST_TIMEOUT = 15e3;
const TIMEOUT = 5e3;
const RETRY_AFTER = 5e3;
const REFRESH_AFTER = 1e3;
function workerFile() {
	const candidates = [new URL("./tailwind-worker.js", import.meta.url)];
	for (const url of candidates) try {
		if (fs.existsSync(url)) return url;
	} catch {}
	return null;
}
function stop() {
	if (bridge) bridge.worker.terminate().catch(() => {});
	bridge = null;
	memos.clear();
}
function transportFailed(reason) {
	stop();
	if (restarts++ >= 1) {
		bridge = false;
		warnOnce("tailwind:off", `The Tailwind worker failed twice (${reason}); no-unknown-classes is using the grammar bundled with @shadcn/lint for the rest of this run.`);
	}
	return null;
}
function start() {
	if (bridge) return bridge;
	if (bridge === false) return null;
	const file = workerFile();
	if (!file) {
		bridge = false;
		warnOnce("tailwind:off", "The Tailwind worker script was not found next to @shadcn/lint; no-unknown-classes is using the bundled grammar.");
		return null;
	}
	try {
		const channel = new MessageChannel();
		const worker = new Worker(file, {
			workerData: { port: channel.port2 },
			transferList: [channel.port2]
		});
		worker.on("error", (error) => {
			if (bridge && bridge.worker === worker) transportFailed(error.message);
		});
		worker.on("exit", () => {
			if (bridge && bridge.worker === worker) stop();
		});
		worker.unref();
		channel.port1.unref();
		bridge = {
			worker,
			port: channel.port1,
			nextId: 1,
			cold: true
		};
		return bridge;
	} catch (error) {
		return transportFailed(error.message);
	}
}
function timeoutFor(live) {
	return live.cold ? FIRST_TIMEOUT : TIMEOUT;
}
function ask(cssFile, candidates) {
	const live = start();
	if (!live) return null;
	const id = live.nextId++;
	const shared = new SharedArrayBuffer(4);
	const flag = new Int32Array(shared);
	live.port.postMessage({
		id,
		cssFile,
		candidates,
		shared
	});
	const waited = Atomics.wait(flag, 0, 0, timeoutFor(live));
	live.cold = false;
	if (waited === "timed-out") return transportFailed("timed out");
	const received = receiveMessageOnPort(live.port);
	if (!received || received.message.id !== id) return transportFailed("out-of-order answer");
	restarts = 0;
	return received.message.answer;
}
const memos = /* @__PURE__ */ new Map();
const failed = /* @__PURE__ */ new Map();
function themeFailed(cssFile, reason) {
	failed.set(cssFile, {
		at: Date.now(),
		reason
	});
	memos.delete(cssFile);
	warnOnce(`tailwind:${cssFile}:${reason}`, `The Tailwind theme at ${cssFile} could not be built (${reason}); no-unknown-classes is using the grammar bundled with @shadcn/lint there until it can.`);
	return null;
}
function unknownClasses(cssFile, candidates) {
	if (bridge === false) return null;
	const failure = failed.get(cssFile);
	if (failure) {
		if (Date.now() - failure.at < RETRY_AFTER) return null;
		failed.delete(cssFile);
	}
	const now = Date.now();
	let memo = memos.get(cssFile);
	const stale = !memo || now - memo.checkedAt >= REFRESH_AFTER;
	let unseen = candidates.filter((c) => !memo?.verdicts.has(c));
	if (unseen.length || stale) {
		let answer = ask(cssFile, [...new Set(unseen)]);
		if (!answer) return null;
		if (!answer.ok) return themeFailed(cssFile, answer.reason);
		if (!memo || memo.generation !== answer.generation) {
			const rebuild = Boolean(memo && answer.hasModules);
			if (rebuild) stop();
			unseen = [...new Set(candidates)];
			if (rebuild || unseen.length) {
				answer = ask(cssFile, unseen);
				if (!answer) return null;
				if (!answer.ok) return themeFailed(cssFile, answer.reason);
			}
			memo = {
				generation: answer.generation,
				checkedAt: now,
				hasModules: answer.hasModules,
				verdicts: /* @__PURE__ */ new Map()
			};
			memos.set(cssFile, memo);
		}
		memo.checkedAt = now;
		for (const token of unseen) memo.verdicts.set(token, true);
		for (const entry of answer.unknown) memo.verdicts.set(entry.token, entry);
	}
	const out = [];
	for (const token of candidates) {
		const verdict = memo.verdicts.get(token);
		if (verdict !== true && verdict !== void 0) out.push(verdict);
	}
	return out;
}

//#endregion
//#region src/rules/no-raw-colors.ts
const NAMED = /* @__PURE__ */ new Set([
	"white",
	"black",
	"transparent",
	"current",
	"inherit"
]);
const COLOR_ATTRIBUTES = /* @__PURE__ */ new Set([
	"fill",
	"stroke",
	"color",
	"stopColor",
	"floodColor",
	"lightingColor"
]);
const ATTRIBUTE_ALLOWED = /* @__PURE__ */ new Set([
	"currentColor",
	"currentcolor",
	"none",
	"inherit",
	"transparent",
	"initial",
	"unset"
]);
const COLOR_FUNCTION = /^(?:#[0-9a-fA-F]{3,8}|(?:rgb|rgba|hsl|hsla|hwb|oklch|oklab|lab|lch|color|color-mix)\(.*\))$/;
function isRawColorValue(value) {
	const trimmed = value.trim();
	if (ATTRIBUTE_ALLOWED.has(trimmed)) return false;
	if (COLOR_FUNCTION.test(trimmed)) return true;
	return isNamedColor(trimmed);
}
function splitColorClass(token) {
	const base = normalizeClass(token);
	const match = base.match(COLOR_PREFIX);
	if (!match) return null;
	const rest = base.slice(match[0].length);
	const opacity = rest.match(OPACITY_MODIFIER)?.[0] ?? "";
	const value = rest.slice(0, rest.length - opacity.length);
	if (!value || value.startsWith("[") || value.startsWith("(")) return null;
	return {
		prefix: match[0],
		value,
		opacity
	};
}
function colorValueOf(token) {
	return splitColorClass(token)?.value ?? null;
}
const PREFIX_NAMESPACES = {
	bg: "background-color",
	text: "text-color",
	border: "border-color",
	divide: "divide-color",
	ring: "ring-color",
	outline: "outline-color",
	accent: "accent-color",
	caret: "caret-color",
	placeholder: "placeholder-color",
	decoration: "text-decoration-color",
	"text-shadow": "text-shadow-color",
	"drop-shadow": "drop-shadow-color",
	fill: "fill",
	stroke: "stroke"
};
function colorNamespaceOf(prefix) {
	const base = prefix.replace(/-$/, "");
	return PREFIX_NAMESPACES[base] ?? PREFIX_NAMESPACES[base.replace(/-(?:[trblxyse]|[bi][se])$/, "")] ?? null;
}
const NO_THEME = {};
const verdicts = /* @__PURE__ */ new WeakMap();
function verdictMemo(theme, key) {
	let byKey = verdicts.get(theme);
	if (!byKey) {
		byKey = /* @__PURE__ */ new Map();
		verdicts.set(theme, byKey);
	}
	let memo = byKey.get(key);
	if (!memo) {
		memo = /* @__PURE__ */ new Map();
		byKey.set(key, memo);
	}
	return memo;
}
const MESSAGES$3 = {
	paletteClass: "\"{{className}}\" uses the raw Tailwind palette. Use a theme token, or define one for this color.",
	paletteClassNear: "\"{{className}}\" uses the raw Tailwind palette. Nearest theme tokens: {{suggestions}}. Use one of those, or declare --color-<name> in {{file}} for a new color.",
	paletteClassFar: "\"{{className}}\" uses the raw Tailwind palette and no declared theme color is close to it. Use one of: {{tokens}}, or declare --color-<name> in {{file}} for a new color.",
	paletteClassListed: "\"{{className}}\" uses the raw Tailwind palette. Use one of the theme colors: {{tokens}}, or declare --color-<name> in {{file}} for a new color.",
	undeclaredToken: "\"{{className}}\" is not a declared theme color. Use one of: {{tokens}}. To add a color, declare --color-<name> in {{file}} first.",
	undeclaredTokenTypo: "\"{{className}}\" is not a declared theme color. Did you mean \"{{suggestion}}\"? Declared colors: {{tokens}}.",
	rawColorAttribute: "{{attribute}}=\"{{value}}\" hardcodes a color. Use currentColor with a text color class, or var(--color-<token>).",
	rawColorAttributeNear: "{{attribute}}=\"{{value}}\" hardcodes a color. Use currentColor with a text color class, or the nearest theme token: var(--color-{{suggestion}}).",
	useToken: "Replace with \"{{replacement}}\"."
};
const noRawColors = {
	meta: {
		type: "problem",
		hasSuggestions: true,
		docs: {
			description: "Require theme tokens for color utilities instead of the raw Tailwind palette.",
			url: "https://github.com/shadcn-ui/lint/blob/main/docs/rules/no-raw-colors.md"
		},
		schema: [{
			type: "object",
			properties: {
				...policySchema,
				...recognitionSchema,
				scanAllStrings: { type: "boolean" }
			},
			additionalProperties: false
		}],
		messages: MESSAGES$3
	},
	create(context) {
		const options = withSettings(context, context.options?.[0] ?? {});
		const emit = reporter(context, MESSAGES$3, {
			rule: "shadcn/no-raw-colors",
			message: options.message
		});
		const filename = fileOf(context);
		let policy;
		try {
			policy = compileVocabularyPolicy({
				...options,
				fromFile: filename
			}, "shadcn/no-raw-colors");
		} catch (error) {
			return configErrorVisitors(context, error);
		}
		const { groupOf } = projectClassifierFor(filename);
		let theme;
		function readTheme() {
			const declared = colorTokensFor(filename);
			const themeFile = themeFileFor(filename);
			const file = themeFile ? displayPath(themeFile, context) : "your theme CSS";
			return {
				declared,
				scoped: scopedColorTokensFor(filename),
				entry: tailwindEntryFor(filename),
				file,
				memo: verdictMemo(declared ?? NO_THEME, file)
			};
		}
		const themeFor = () => theme ??= readTheme();
		let listed;
		const tokenList = () => listed ??= themeFor().declared ? listTokens(themeFor().declared) : "";
		let colors;
		const suggestionColors = () => {
			if (colors === void 0) colors = themeFor().declared ? colorValuesFor(filename) : null;
			return colors;
		};
		const nearest = (token) => {
			const parts = splitColorClass(token);
			const lab = parts && paletteColor(parts.value);
			const values = suggestionColors();
			if (!parts || !lab || !values) return [];
			return nearestColorTokens(lab, values, roleOf(parts.prefix)).map((name) => withBase(token, `${parts.prefix}${name}${parts.opacity}`));
		};
		const paletteVerdict = (token) => {
			const { declared, file } = themeFor();
			if (!declared) return {
				messageId: "paletteClass",
				data: { className: token }
			};
			if (!suggestionColors()?.size) return {
				messageId: "paletteClassListed",
				data: {
					className: token,
					tokens: tokenList(),
					file
				}
			};
			const suggestions = nearest(token);
			return {
				messageId: suggestions.length ? "paletteClassNear" : "paletteClassFar",
				data: {
					className: token,
					suggestions: suggestions.join(", "),
					tokens: tokenList(),
					file
				},
				replacements: suggestions
			};
		};
		const isTypoOfAnotherUtility = (token) => {
			const { entry } = themeFor();
			const suggestion = (entry ? unknownClasses(entry, [token]) : null)?.[0]?.suggestion;
			return !!suggestion && categoryOf(groupOf(suggestion)) !== "color";
		};
		const tokensFor = (prefix) => {
			const { declared, scoped } = themeFor();
			const namespace = colorNamespaceOf(prefix);
			const own = namespace ? scoped?.get(namespace) : null;
			if (!own?.size) return declared;
			return /* @__PURE__ */ new Set([...declared ?? [], ...own]);
		};
		const undeclaredVerdict = (token) => {
			const { file } = themeFor();
			const parts = splitColorClass(token);
			const declared = parts ? tokensFor(parts.prefix) : null;
			const meant = parts && declared ? didYouMean(parts.value, declared) : null;
			if (!meant && isTypoOfAnotherUtility(token)) return null;
			if (parts && meant) {
				const suggestion = withBase(token, `${parts.prefix}${meant}${parts.opacity}`);
				return {
					messageId: "undeclaredTokenTypo",
					data: {
						className: token,
						suggestion,
						tokens: tokenList(),
						file
					},
					replacements: [suggestion]
				};
			}
			return {
				messageId: "undeclaredToken",
				data: {
					className: token,
					tokens: tokenList(),
					file
				}
			};
		};
		const judge = (token) => {
			if (isArbitraryValue$1(token)) return null;
			const { declared } = themeFor();
			const parts = splitColorClass(token);
			const colorValue = parts?.value ?? null;
			if (colorValue && declared?.has(colorValue)) return null;
			if (parts && tokensFor(parts.prefix)?.has(parts.value)) return null;
			if (isPaletteClass(token)) return paletteVerdict(token);
			if (!declared) return null;
			if (categoryOf(groupOf(token)) !== "color") return null;
			if (!colorValue || NAMED.has(colorValue)) return null;
			if (declaresUtility(filename, token)) return null;
			return undeclaredVerdict(token);
		};
		const verdictOf = (token) => {
			const { memo } = themeFor();
			let verdict = memo.get(token);
			if (verdict === void 0) {
				if (memo.size > 5e4) memo.clear();
				verdict = judge(token);
				memo.set(token, verdict);
			}
			return verdict;
		};
		const visitors = classSiteVisitors(context, options, (site) => {
			for (const { value, node } of site.vocabularyStrings) for (const token of splitClasses(value)) {
				const verdict = verdictOf(token);
				if (!verdict) continue;
				const exemption = policy.decide(site.component, token);
				if (exemption.kind === "ok") continue;
				const { replacements, ...report } = verdict;
				emit({
					node,
					...report,
					data: {
						...report.data,
						component: site.component ?? ""
					},
					suggest: classSuggestions(node, context, token, replacements ?? [], "useToken", "replacement")
				}, exemption.message);
			}
		});
		const reader = readerFor(context);
		const colorAttribute = (node) => {
			const name = reader.attributeName(node);
			if (!COLOR_ATTRIBUTES.has(name)) return;
			const tag = reader.nameOf(reader.elementOf(node));
			if (!tag || tag.component || !/^[a-z]/.test(tag.root)) return;
			const value = staticStringOf(reader.attributeValue(node));
			if (value === null || !isRawColorValue(value)) return;
			const values = suggestionColors();
			const lab = values?.size ? parseColor(value) : null;
			const [suggestion] = lab ? nearestColorTokens(lab, values, "text", 1) : [];
			emit({
				node,
				messageId: suggestion ? "rawColorAttributeNear" : "rawColorAttribute",
				data: {
					attribute: name,
					value,
					suggestion: suggestion ?? ""
				}
			});
		};
		const merged = { ...visitors };
		for (const type of reader.attributes) {
			const classAttribute = visitors[type];
			merged[type] = (node) => {
				classAttribute?.(node);
				colorAttribute(node);
			};
		}
		return merged;
	}
};

//#endregion
//#region src/project/variants.ts
const cache = /* @__PURE__ */ new Map();
const VARIANT_FACTORIES = /* @__PURE__ */ new Set(["cva", "tv"]);
function keyName(node) {
	if (node.type === "Identifier") return node.name;
	if (node.type === "Literal" && typeof node.value === "string") return node.value;
	return null;
}
function axesOf(config) {
	const axes = {};
	if (config?.type !== "ObjectExpression") return axes;
	const variants = config.properties.find((p) => p.type === "Property" && keyName(p.key) === "variants");
	if (variants?.value?.type !== "ObjectExpression") return axes;
	for (const axis of variants.value.properties) {
		if (axis.type !== "Property") continue;
		const axisName = keyName(axis.key);
		if (!axisName || axis.value?.type !== "ObjectExpression") continue;
		axes[axisName] = axis.value.properties.filter((p) => p.type === "Property").map((p) => keyName(p.key)).filter((k) => typeof k === "string");
	}
	return axes;
}
const MAY_DEFINE_VARIANTS = /\b(?:cva|tv)\s*\(|\|\s*["']|\bkeyof\s+typeof\b/;
const MAX_TYPE_DEPTH = 8;
function unwrapType(type) {
	let out = type;
	for (let depth = 0; out?.type === "TSParenthesizedType" && depth < MAX_TYPE_DEPTH; depth++) out = out.typeAnnotation;
	return out;
}
function objectKeys(object) {
	if (object?.type !== "ObjectExpression") return null;
	const keys = [];
	for (const property of object.properties) {
		if (property.type !== "Property" || property.computed) return null;
		const key = keyName(property.key);
		if (!key) return null;
		keys.push(key);
	}
	return keys.length ? keys : null;
}
function literalValues(input, declared, depth = 0) {
	const type = unwrapType(input);
	if (!type || depth > MAX_TYPE_DEPTH) return null;
	if (type.type === "TSTypeReference" && type.typeName?.type === "Identifier") return literalValues(declared.types.get(type.typeName.name), declared, depth + 1);
	if (type.type === "TSTypeOperator" && type.operator === "keyof" && type.typeAnnotation?.type === "TSTypeQuery" && type.typeAnnotation.exprName?.type === "Identifier") return objectKeys(declared.objects.get(type.typeAnnotation.exprName.name));
	if (type.type === "TSUnionType") {
		const values = [];
		for (const member of type.types) {
			if (member.type === "TSUndefinedKeyword") continue;
			const nested = literalValues(member, declared, depth + 1);
			if (!nested) return null;
			values.push(...nested);
		}
		return values.length ? values : null;
	}
	if (type.type === "TSLiteralType" && type.literal?.type === "Literal" && typeof type.literal.value === "string") return [type.literal.value];
	return null;
}
function axesOfPropsType(input, declared, depth = 0) {
	const axes = {};
	const type = unwrapType(input);
	if (!type || depth > MAX_TYPE_DEPTH) return axes;
	if (type.type === "TSIntersectionType") {
		for (const member of type.types) Object.assign(axes, axesOfPropsType(member, declared, depth + 1));
		return axes;
	}
	if (type.type === "TSUnionType") {
		const [first, ...rest] = type.types.map((member) => axesOfPropsType(member, declared, depth + 1));
		for (const [name, values] of Object.entries(first ?? {})) {
			const shared = values.filter((value) => rest.every((other) => other[name]?.includes(value)));
			if (shared.length) axes[name] = shared;
		}
		return axes;
	}
	if (type.type === "TSTypeReference" && type.typeName?.type === "Identifier") return axesOfPropsType(declared.types.get(type.typeName.name), declared, depth + 1);
	const members = type.type === "TSTypeLiteral" ? type.members : type.type === "TSInterfaceBody" ? type.body : null;
	if (!members) return axes;
	for (const member of members) {
		if (member.type !== "TSPropertySignature") continue;
		const key = keyName(member.key);
		const values = literalValues(member.typeAnnotation?.typeAnnotation, declared);
		if (key && values) axes[key] = values;
	}
	return axes;
}
function declarationsIn(ast) {
	const types = /* @__PURE__ */ new Map();
	const objects = /* @__PURE__ */ new Map();
	walk(ast, (node) => {
		if (node.type === "TSTypeAliasDeclaration" && node.id?.type === "Identifier") types.set(node.id.name, node.typeAnnotation);
		else if (node.type === "TSInterfaceDeclaration" && node.id?.type === "Identifier") types.set(node.id.name, node.body);
		else if (node.type === "VariableDeclarator" && node.id?.type === "Identifier") {
			const init = node.init?.type === "TSAsExpression" || node.init?.type === "TSSatisfiesExpression" ? node.init.expression : node.init;
			if (init?.type === "ObjectExpression") objects.set(node.id.name, init);
		}
	});
	return {
		types,
		objects
	};
}
function componentSignature(node) {
	if (node.type === "FunctionDeclaration" && node.id?.type === "Identifier") return {
		name: node.id.name,
		param: node.params?.[0]
	};
	if (node.type === "VariableDeclarator" && node.id?.type === "Identifier" && (node.init?.type === "ArrowFunctionExpression" || node.init?.type === "FunctionExpression")) return {
		name: node.id.name,
		param: node.init.params?.[0]
	};
	return null;
}
function extractVariantDefinitions(source, file = "x.tsx") {
	const definitions = [];
	if (!MAY_DEFINE_VARIANTS.test(source)) return definitions;
	let ast;
	try {
		ast = parseSource(source, file);
	} catch {
		return definitions;
	}
	const declared = declarationsIn(ast);
	walk(ast, (node, parent) => {
		if (node.type === "CallExpression") {
			if (node.callee?.type !== "Identifier") return;
			if (!VARIANT_FACTORIES.has(node.callee.name)) return;
			const [first, second] = node.arguments;
			const axes = axesOf(node.callee.name === "tv" && first?.type === "ObjectExpression" ? first : second);
			if (!Object.keys(axes).length) return;
			const name = parent?.type === "VariableDeclarator" && parent.id?.type === "Identifier" ? parent.id.name : null;
			definitions.push({
				name,
				axes,
				source: "factory"
			});
			return;
		}
		const signature = componentSignature(node);
		if (!signature) return;
		const type = signature.param?.typeAnnotation?.typeAnnotation;
		const axes = axesOfPropsType(type, declared);
		if (!Object.keys(axes).length) return;
		definitions.push({
			name: signature.name,
			axes,
			source: "props"
		});
	});
	return definitions;
}
function variantDefinitionsOf(file) {
	const mtimeMs = mtimeOf(file);
	if (mtimeMs === null) return [];
	const cached = cache.get(file);
	if (cached && cached.mtimeMs === mtimeMs) return cached.definitions;
	let definitions = [];
	try {
		definitions = extractVariantDefinitions(fs.readFileSync(file, "utf-8"), file);
	} catch {
		definitions = [];
	}
	cache.set(file, {
		mtimeMs,
		definitions
	});
	return definitions;
}
function definitionFor(file, component) {
	const expected = component.charAt(0).toLowerCase() + component.slice(1) + "Variants";
	const definitions = variantDefinitionsOf(file);
	if (!definitions.length) {
		const barrel = isSfc(file) ? barrelOf(path.dirname(file)) : null;
		if (!barrel) return null;
		if (![...exportsOf(barrel).values()].some((binding) => binding.file === file)) return null;
		return variantDefinitionsOf(barrel).find((d) => d.name === expected) ?? null;
	}
	return definitions.find((d) => d.name === expected) ?? definitions.find((d) => d.name === component && d.source === "props") ?? definitions.find((d) => d.source === "factory") ?? null;
}
function variantNamesFor(file, component) {
	const values = definitionFor(file, component)?.axes.variant;
	return values?.length ? values : null;
}
function sizeNamesFor(file, component) {
	const values = definitionFor(file, component)?.axes.size;
	return values?.length ? values : null;
}

//#endregion
//#region src/rules/no-restyle.ts
const messageSchema = { anyOf: [{
	type: "string",
	maxLength: 500
}, {
	type: "object",
	properties: Object.fromEntries([
		"default",
		"layout",
		...CATEGORIES
	].map((key) => [key, {
		type: "string",
		maxLength: 500
	}])),
	additionalProperties: false
}] };
const NOT_ALLOWED = "\"{{className}}\" is not allowed on <{{component}}>:";
const OWNS = "<{{component}}> owns its {{category}}.";
const OWNS_VIA_WRAPPER = "<{{wrapper}}> forwards className to <{{component}}>, which owns its {{category}}.";
const NEW_VARIANT_GUARD = "only if the design explicitly calls for a treatment none of these provides.";
const SPACING_SIZES = "Use a size ({{sizes}}), or {{around}} for space around it.";
const SPACING_AROUND = "For space around it, use {{around}}.";
const SPACING_NEW_SIZE = "Add a size in {{file}} only if the design explicitly calls for one.";
const MESSAGES$2 = {
	appearanceClass: `${NOT_ALLOWED} ${OWNS} Use one of its variants. Add a new variant only if the design explicitly calls for a treatment none of them provides.`,
	appearanceClassWithVariants: `${NOT_ALLOWED} ${OWNS} Use a variant: {{variants}}. Add a new variant in {{file}} ${NEW_VARIANT_GUARD}`,
	appearanceClassNoVariants: `${NOT_ALLOWED} ${OWNS} Add a variant in {{file}} only if the design explicitly calls for this treatment.`,
	appearanceClassViaWrapper: `"{{className}}" is not allowed on <{{wrapper}}>: ${OWNS_VIA_WRAPPER} Use a variant{{variantsSuffix}}. Add a new variant {{where}} ${NEW_VARIANT_GUARD}`,
	deniedClass: `${NOT_ALLOWED} its contract denies {{entries}}.`,
	layoutClass: `${NOT_ALLOWED} its contract allows {{entries}}. Use one of those, or put layout classes on a parent element.`,
	layoutClassClosed: `${NOT_ALLOWED} its contract allows no classes. Put layout classes on a parent element instead.`,
	unclassifiedClass: `${NOT_ALLOWED} the grammar does not recognize it. Fix the spelling, or use a class Tailwind generates.`,
	declaredClass: `${NOT_ALLOWED} your CSS declares it, and the grammar cannot tell what it changes. Use a variant, or put it on a parent element.`,
	spacingClassWithSizes: `${NOT_ALLOWED} ${OWNS} ${SPACING_SIZES} ${SPACING_NEW_SIZE}`,
	spacingClassNoSizes: `${NOT_ALLOWED} ${OWNS} ${SPACING_AROUND}`,
	spacingClassViaWrapperWithSizes: `"{{className}}" is not allowed on <{{wrapper}}>: ${OWNS_VIA_WRAPPER} ${SPACING_SIZES} ${SPACING_NEW_SIZE}`,
	spacingClassViaWrapperNoSizes: `"{{className}}" is not allowed on <{{wrapper}}>: ${OWNS_VIA_WRAPPER} ${SPACING_AROUND}`
};
const noRestyle = {
	meta: {
		type: "problem",
		docs: {
			description: "Disallow classes on design-system components except what the rule's allow list and the component's contract permit.",
			url: "https://github.com/shadcn-ui/lint/blob/main/docs/rules/no-restyle.md"
		},
		schema: [{
			type: "object",
			properties: {
				allow: entriesSchema,
				deny: entriesSchema,
				message: messageSchema,
				...recognitionSchema,
				contracts: {
					type: "array",
					items: {
						type: "object",
						properties: {
							pattern: { type: "string" },
							allow: entriesSchema,
							deny: entriesSchema,
							message: messageSchema
						},
						required: ["pattern"],
						additionalProperties: false
					}
				}
			},
			additionalProperties: false
		}],
		messages: MESSAGES$2
	},
	create(context) {
		const emit = reporter(context, MESSAGES$2);
		const options = withSettings(context, context.options?.[0] ?? {});
		const filename = fileOf(context);
		let contracts;
		try {
			contracts = compileContracts(options.contracts, {
				allow: options.allow,
				deny: options.deny,
				message: options.message,
				fromFile: filename
			});
		} catch (error) {
			return configErrorVisitors(context, error);
		}
		return classSiteVisitors(context, options, (site) => {
			if (!site.component) return;
			const component = site.component;
			const file = site.componentFile;
			const where = file ? displayPath(file, context) : "";
			let details;
			for (const { value, node } of site.contextualStrings) for (const token of splitClasses(value)) {
				const verdict = contracts.decide(component, token);
				if (verdict.kind === "ok") continue;
				details ??= appearanceDetails(site);
				const { messageId, variantNames, variantsSuffix } = details;
				const data = {
					className: token,
					component,
					entries: verdict.entries.join(" "),
					category: verdict.category,
					variants: variantNames,
					wrapper: site.wrapper ?? "",
					file: where
				};
				if (verdict.kind === "denied" || verdict.category === "layout" || verdict.category === "unclassified") emit({
					node,
					messageId: verdict.kind === "denied" ? "deniedClass" : verdict.category === "unclassified" ? declaresClass(filename, token) ? "declaredClass" : "unclassifiedClass" : verdict.entries.length ? "layoutClass" : "layoutClassClosed",
					data
				}, verdict.message);
				else if (verdict.category === "spacing") {
					const sizes = file ? sizeNamesFor(file, component) : null;
					emit({
						node,
						messageId: site.wrapper ? sizes ? "spacingClassViaWrapperWithSizes" : "spacingClassViaWrapperNoSizes" : sizes ? "spacingClassWithSizes" : "spacingClassNoSizes",
						data: {
							...data,
							sizes: sizes?.join(", ") ?? "",
							around: aroundFor(site, contracts, component, token, filename)
						}
					}, verdict.message);
				} else emit({
					node,
					messageId,
					data: {
						...data,
						variantsSuffix,
						where: where ? `in ${where}` : `to <${component}>`
					}
				}, verdict.message);
			}
		});
	}
};
function aroundFor(site, contracts, component, token, filename) {
	const accepts = (name) => contracts.decide(name, token).kind === "ok";
	const places = [];
	if (contracts.decide(component, "m-4").kind === "ok") places.push("margin here");
	const container = site.enclosingContainer(accepts);
	if (!container?.direct) places.push(site.closedParent(accepts) ? "gap on a plain wrapper around it" : "gap on the parent");
	if (container) places.push(`spacing on <${container.name}>`);
	const primitives = contracts.primitivesFor(token, container ? [component, container.name] : [component], () => filename ? componentsFor(filename).files.keys() : []);
	if (primitives.length) places.push(listOf(primitives));
	const last = places.pop();
	if (!places.length) return last;
	if (places.length === 1) return `${places[0]} or ${last}`;
	return `${places.join(", ")}, or ${last}`;
}
function listOf(names) {
	if (names.length < 3) return names.join(" and ");
	return `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}
function appearanceDetails(site) {
	const variants = site.componentFile ? variantNamesFor(site.componentFile, site.component) : null;
	const messageId = site.wrapper ? "appearanceClassViaWrapper" : !site.componentFile ? "appearanceClass" : variants ? "appearanceClassWithVariants" : "appearanceClassNoVariants";
	const variantNames = variants?.join(", ") ?? "";
	return {
		messageId,
		variantNames,
		variantsSuffix: variantNames ? `: ${variantNames}` : ""
	};
}

//#endregion
//#region src/rules/no-unknown-classes.ts
const MESSAGES$1 = {
	unknownClass: "\"{{className}}\" is not a class this project's Tailwind knows, so no CSS is generated for it. Fix the spelling, or declare it with @utility in {{file}}.",
	unknownClassSuggest: "\"{{className}}\" is not a class this project's Tailwind knows, so no CSS is generated for it. Did you mean \"{{suggestion}}\"?",
	unknownVariant: "\"{{className}}\" uses a variant this project's Tailwind does not know, so no CSS is generated for it. Use an existing variant, or declare it with @custom-variant in {{file}}.",
	useSuggestion: "Replace with \"{{suggestion}}\"."
};
const noUnknownClasses = {
	meta: {
		type: "problem",
		hasSuggestions: true,
		docs: {
			description: "Disallow classes Tailwind does not know; no CSS is generated for them.",
			url: "https://github.com/shadcn-ui/lint/blob/main/docs/rules/no-unknown-classes.md"
		},
		schema: [{
			type: "object",
			properties: {
				...policySchema,
				...recognitionSchema
			},
			additionalProperties: false
		}],
		messages: MESSAGES$1
	},
	create(context) {
		const options = withSettings(context, context.options?.[0] ?? {});
		const emit = reporter(context, MESSAGES$1, {
			rule: "shadcn/no-unknown-classes",
			message: options.message
		});
		const filename = fileOf(context);
		let policy;
		try {
			policy = compileVocabularyPolicy({
				...options,
				uncheckedEntries: true,
				fromFile: filename
			}, "shadcn/no-unknown-classes");
		} catch (error) {
			return configErrorVisitors(context, error);
		}
		const { groupOf } = projectClassifierFor(filename);
		const known = knownClassesFor(filename);
		const ownClasses = isSfc(filename) ? styleClassesOf(context.sourceCode?.text ?? "") : /* @__PURE__ */ new Set();
		const themeFile = themeFileFor(filename);
		const file = themeFile ? displayPath(themeFile, context) : "your theme CSS";
		const entry = tailwindEntryFor(filename);
		const utilityPrefixes = utilityPrefixesOf(known.utilities);
		const settled = (token) => {
			const base = normalizeClass(token);
			if (!base) return true;
			if (base.startsWith("[")) return true;
			if (isMarkerClass(token)) return true;
			const bare = base.replace(/\/[\w.%]+$/, "");
			return known.classes.has(bare) || ownClasses.has(bare);
		};
		const knownByGrammar = (token) => {
			if (groupOf(token)) return true;
			const bare = normalizeClass(token).replace(/\/[\w.%]+$/, "");
			if (known.utilities.has(bare)) return true;
			return utilityPrefixes.some((prefix) => bare.startsWith(prefix));
		};
		const report = (node, token, suggestion, words, component, variantOnly = false) => {
			emit({
				node,
				messageId: suggestion ? "unknownClassSuggest" : variantOnly ? "unknownVariant" : "unknownClass",
				data: {
					className: token,
					component,
					file,
					suggestion: suggestion ?? ""
				},
				suggest: suggestion ? classSuggestions(node, context, token, [suggestion], "useSuggestion", "suggestion") : void 0
			}, words);
		};
		const isColor = (token) => categoryOf(groupOf(token)) === "color";
		let declared;
		const ownsColorTypo = (token, suggestion) => {
			if (!suggestion || isColor(suggestion)) return false;
			const value = colorValueOf(token);
			if (!value) return true;
			declared ??= colorTokensFor(filename);
			return !declared || !didYouMean(value, declared);
		};
		return classSiteVisitors(context, options, (site) => {
			for (const { value, node } of site.vocabularyStrings) {
				const wordsFor = /* @__PURE__ */ new Map();
				const tokens = splitClasses(value).filter((token) => {
					if (settled(token)) return false;
					const exemption = policy.decide(site.component, token);
					if (exemption.kind === "ok") return false;
					wordsFor.set(token, exemption.message);
					return true;
				});
				if (!tokens.length) continue;
				const asked = entry ? unknownClasses(entry, tokens) : null;
				if (asked) {
					for (const { token, suggestion, baseKnown } of asked) {
						if (isColor(token) && !baseKnown && !ownsColorTypo(token, suggestion)) continue;
						report(node, token, suggestion, wordsFor.get(token) ?? null, site.component ?? "", baseKnown && token.includes(":"));
					}
					continue;
				}
				for (const token of tokens) if (!knownByGrammar(token)) report(node, token, null, wordsFor.get(token) ?? null, site.component ?? "");
			}
		});
	}
};

//#endregion
//#region src/rules/require-static-classes.ts
const MESSAGES = { dynamicClasses: "Dynamically built className on <{{component}}> cannot be checked. Use static class strings." };
const requireStaticClasses = {
	meta: {
		type: "problem",
		docs: {
			description: "Require statically analyzable className values on design-system components.",
			url: "https://github.com/shadcn-ui/lint/blob/main/docs/rules/require-static-classes.md"
		},
		schema: [{
			type: "object",
			properties: {
				message: {
					type: "string",
					maxLength: 500
				},
				...recognitionSchema
			},
			additionalProperties: false
		}],
		messages: MESSAGES
	},
	create(context) {
		const options = withSettings(context, context.options?.[0] ?? {});
		const emit = reporter(context, MESSAGES, {
			rule: "shadcn/require-static-classes",
			message: options.message
		});
		return classSiteVisitors(context, options, (site) => {
			if (!site.component) return;
			for (const node of site.unresolved) emit({
				node,
				messageId: "dynamicClasses",
				data: { component: site.component }
			});
		});
	}
};

//#endregion
//#region src/plugin.ts
const rules = {
	"no-restyle": withTemplates(noRestyle),
	"no-raw-colors": withTemplates(noRawColors),
	"no-arbitrary-values": withTemplates(noArbitraryValues),
	"no-inline-styles": withTemplates(noInlineStyles),
	"require-static-classes": withTemplates(requireStaticClasses),
	"no-unknown-classes": withTemplates(noUnknownClasses)
};
const plugin = {
	meta: { name: "shadcn" },
	rules
};

//#endregion
//#region src/index.ts
const project = {
	projectFor,
	themeFileFor,
	colorTokensFor,
	componentsFor,
	variantDefinitionsOf,
	variantNamesFor
};
var src_default = plugin;

//#endregion
export { src_default as default, plugin, project };
