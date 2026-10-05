// Licensed source: eslint-plugin-astro 3.2.1 (MIT). See LICENSE.
//#region src/utils/style/tokenizer.ts
const EOF = -1;
const NULL = 0;
const TABULATION = 9;
const CARRIAGE_RETURN = 13;
const LINE_FEED = 10;
const FORM_FEED = 12;
const SPACE = 32;
const QUOTATION_MARK = 34;
const APOSTROPHE = 39;
const LEFT_PARENTHESIS = 40;
const RIGHT_PARENTHESIS = 41;
const ASTERISK = 42;
const COMMA = 44;
const SOLIDUS = 47;
const COLON = 58;
const SEMICOLON = 59;
const LEFT_SQUARE_BRACKET = 91;
const REVERSE_SOLIDUS = 92;
const RIGHT_SQUARE_BRACKET = 93;
const LEFT_CURLY_BRACKET = 123;
const RIGHT_CURLY_BRACKET = 125;
/**
* Check whether the code point is a whitespace.
* @param cp The code point to check.
* @returns `true` if the code point is a whitespace.
*/
function isWhitespace(cp) {
	return cp === TABULATION || cp === LINE_FEED || cp === FORM_FEED || cp === CARRIAGE_RETURN || cp === SPACE;
}
/**
* A simplified CSS tokenizer.
* The tokenizer is implemented with reference to the CSS specification,
* but it does not follow it. This tokenizer only does the tokenization needed to properly handle `v-bind()`.
* @see https://drafts.csswg.org/css-syntax/#tokenization
*/
var CSSTokenizer = class {
	text;
	options;
	cp;
	offset;
	nextOffset;
	reconsuming;
	/**
	* Initialize this tokenizer.
	* @param text The source code to tokenize.
	* @param options The tokenizer options.
	*/
	constructor(text, startOffset, options) {
		this.text = text;
		this.options = { inlineComment: options?.inlineComment ?? false };
		this.cp = NULL;
		this.offset = startOffset - 1;
		this.nextOffset = startOffset;
		this.reconsuming = false;
	}
	/**
	* Get the next token.
	* @returns The next token or null.
	*/
	nextToken() {
		let cp;
		if (this.reconsuming) {
			cp = this.cp;
			this.reconsuming = false;
		} else cp = this.consumeNextCodePoint();
		while (isWhitespace(cp)) cp = this.consumeNextCodePoint();
		if (cp === EOF) return null;
		const start = this.offset;
		return this.consumeNextToken(cp, start);
	}
	/**
	* Get the next code point.
	* @returns The code point.
	*/
	nextCodePoint() {
		if (this.nextOffset >= this.text.length) return EOF;
		return this.text.codePointAt(this.nextOffset);
	}
	/**
	* Consume the next code point.
	* @returns The consumed code point.
	*/
	consumeNextCodePoint() {
		if (this.offset >= this.text.length) {
			this.cp = EOF;
			return EOF;
		}
		this.offset = this.nextOffset;
		if (this.offset >= this.text.length) {
			this.cp = EOF;
			return EOF;
		}
		let cp = this.text.codePointAt(this.offset);
		if (cp === CARRIAGE_RETURN) {
			this.nextOffset = this.offset + 1;
			if (this.text.codePointAt(this.nextOffset) === LINE_FEED) this.nextOffset++;
			cp = LINE_FEED;
		} else this.nextOffset = this.offset + (cp >= 65536 ? 2 : 1);
		this.cp = cp;
		return cp;
	}
	consumeNextToken(cp, start) {
		if (cp === SOLIDUS) {
			const nextCp = this.nextCodePoint();
			if (nextCp === ASTERISK) return this.consumeComment(start);
			if (nextCp === SOLIDUS && this.options.inlineComment) return this.consumeInlineComment(start);
		}
		if (isQuote(cp)) return this.consumeString(start, cp);
		if (isPunctuator(cp)) return {
			type: "Punctuator",
			range: [start, start + 1],
			value: String.fromCodePoint(cp)
		};
		return this.consumeWord(start);
	}
	/**
	* Consume word
	*/
	consumeWord(start) {
		let cp = this.consumeNextCodePoint();
		while (!isWhitespace(cp) && !isPunctuator(cp) && !isQuote(cp)) cp = this.consumeNextCodePoint();
		this.reconsuming = true;
		const range = [start, this.offset];
		const text = this.text;
		let value;
		return {
			type: "Word",
			range,
			get value() {
				return value ?? (value = text.slice(...range));
			}
		};
	}
	/**
	* https://drafts.csswg.org/css-syntax/#consume-string-token
	*/
	consumeString(start, quote) {
		let valueEndOffset = null;
		let cp = this.consumeNextCodePoint();
		while (cp !== EOF) {
			if (cp === quote) {
				valueEndOffset = this.offset;
				break;
			}
			if (cp === REVERSE_SOLIDUS) this.consumeNextCodePoint();
			cp = this.consumeNextCodePoint();
		}
		const text = this.text;
		let value;
		const valueRange = [start + 1, valueEndOffset ?? this.nextOffset];
		return {
			type: "Quoted",
			range: [start, this.nextOffset],
			valueRange,
			get value() {
				return value ?? (value = text.slice(...valueRange));
			},
			quote: String.fromCodePoint(quote)
		};
	}
	/**
	* https://drafts.csswg.org/css-syntax/#consume-comment
	*/
	consumeComment(start) {
		this.consumeNextCodePoint();
		let valueEndOffset = null;
		let cp = this.consumeNextCodePoint();
		while (cp !== EOF) {
			if (cp === ASTERISK) {
				cp = this.consumeNextCodePoint();
				if (cp === SOLIDUS) {
					valueEndOffset = this.offset - 1;
					break;
				}
			}
			cp = this.consumeNextCodePoint();
		}
		const valueRange = [start + 2, valueEndOffset ?? this.nextOffset];
		const text = this.text;
		let value;
		return {
			type: "Block",
			range: [start, this.nextOffset],
			valueRange,
			get value() {
				return value ?? (value = text.slice(...valueRange));
			}
		};
	}
	/**
	* Consume inline comment
	*/
	consumeInlineComment(start) {
		this.consumeNextCodePoint();
		let valueEndOffset = null;
		let cp = this.consumeNextCodePoint();
		while (cp !== EOF) {
			if (cp === LINE_FEED) {
				valueEndOffset = this.offset - 1;
				break;
			}
			cp = this.consumeNextCodePoint();
		}
		const valueRange = [start + 2, valueEndOffset ?? this.nextOffset];
		const text = this.text;
		let value;
		return {
			type: "Line",
			range: [start, this.nextOffset],
			valueRange,
			get value() {
				return value ?? (value = text.slice(...valueRange));
			}
		};
	}
};
/** Checks whether given code point is punctuator */
function isPunctuator(cp) {
	return cp === COLON || cp === SEMICOLON || cp === COMMA || cp === LEFT_PARENTHESIS || cp === RIGHT_PARENTHESIS || cp === LEFT_CURLY_BRACKET || cp === RIGHT_CURLY_BRACKET || cp === LEFT_SQUARE_BRACKET || cp === RIGHT_SQUARE_BRACKET || cp === SOLIDUS || cp === ASTERISK;
}
/** Checks whether given code point is quotes */
function isQuote(cp) {
	return cp === APOSTROPHE || cp === QUOTATION_MARK;
}
//#endregion
//#region src/utils/style/index.ts
var CSSTokenScanner = class {
	reconsuming = [];
	tokenizer;
	constructor(text, options) {
		this.tokenizer = new CSSTokenizer(text, 0, options);
	}
	nextToken() {
		return this.reconsuming.shift() || this.tokenizer.nextToken();
	}
	reconsume(...tokens) {
		this.reconsuming.push(...tokens);
	}
};
/**
* Iterate the CSS variables.
*/
function* iterateCSSVars(code, cssOptions) {
	const tokenizer = new CSSTokenScanner(code, cssOptions);
	let token;
	while (token = tokenizer.nextToken()) if (token.type === "Word" || token.value.startsWith("--")) yield token.value;
}
//#endregion

export { iterateCSSVars };
