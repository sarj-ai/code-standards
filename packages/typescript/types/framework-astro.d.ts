/// <reference lib="esnext.disposable" />

import type { TranspileOutput } from "typescript-native/unstable/sync";

/** UTF-16 offsets in the corresponding original or compiler document. */
export type AstroRange = readonly [start: number, end: number];

export interface AstroSourceSpan {
  readonly virtual: AstroRange;
  readonly original: AstroRange;
  readonly exact: boolean;
}

export interface AstroSourceComment {
  readonly start: number;
  readonly end: number;
  readonly value: string;
  readonly kind: "Line" | "Block" | "html";
}

export interface AstroElement {
  readonly name: string;
  readonly start: number;
  readonly end?: number;
  readonly attributes: readonly {
    readonly name: string;
    readonly kind: string;
    readonly value?: string;
    readonly start: number;
  }[];
  readonly children: readonly {
    readonly type: string;
    readonly value?: string;
    readonly start: number;
    readonly end?: number;
  }[];
}

export interface AstroSourceDocument {
  readonly filename: string;
  readonly text: string;
  readonly virtualHash: string;
  readonly spans: readonly AstroSourceSpan[];
  readonly elements: readonly AstroElement[];
  readonly originalComments: readonly AstroSourceComment[];
}

export interface AstroSourceRegion {
  readonly text: string;
  readonly start: number;
  readonly expression?: boolean;
}

export interface CompiledAstroDocument {
  readonly text: string;
  readonly bindingsText: string;
  readonly origin: AstroSourceDocument;
  readonly frontmatter: AstroSourceRegion | undefined;
  readonly rawRegions: readonly AstroSourceRegion[];
  readonly scripts: readonly (AstroSourceRegion & {
    readonly language: "jsx" | "tsx";
  })[];
  readonly javascript: TranspileOutput;
}

export interface AstroCompiler {
  compile(source: string, filename: string): Promise<CompiledAstroDocument>;
  close(): void;
}

export interface AstroDiagnostic {
  readonly filename: string;
  readonly severity: "error" | "warning";
  readonly message: string;
  readonly code?: string;
  readonly help?: string;
  readonly url?: string;
  readonly labels: readonly {
    readonly label?: string;
    readonly span: {
      readonly offset: number;
      readonly length: number;
      readonly line: number;
      readonly column: number;
    };
  }[];
}

export interface AstroLintOptions {
  readonly filenames: readonly string[];
  readonly configPath: string;
  readonly cwd?: string;
  readonly fix?: boolean;
  readonly fixSuggestions?: boolean;
  readonly typeAware?: boolean;
}

export interface AstroLintReport {
  readonly diagnostics: readonly AstroDiagnostic[];
  readonly "number_of_files": number;
  readonly appliedFixes: number;
  readonly skippedFixes: readonly {
    readonly filename: string;
    readonly reason: string;
  }[];
}

export declare function createAstroCompiler(options?: {
  readonly cwd?: string;
}): AstroCompiler;

export declare function lintAstroFiles(options: AstroLintOptions): Promise<AstroLintReport>;

export declare function mapAstroRange(
  origin: Pick<AstroSourceDocument, "spans">,
  range: AstroRange,
  options?: { readonly exact?: boolean },
): AstroRange | null;

export declare function projectAstroPattern(pattern: string, suffix: string): string;
