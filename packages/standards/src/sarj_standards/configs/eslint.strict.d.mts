// Generated from eslint.strict.ts by compile-eslint.mts.
import type { Linter } from "eslint";
export interface ConfigOptions {
    readonly tsconfigRootDir?: string | URL;
    readonly projectService?: boolean | object;
    readonly syntaxOnlyConfigFiles?: string[];
    readonly testFrameworks?: string[];
    readonly playwrightTestFiles?: string[];
    readonly bunTestFiles?: string[];
}
export declare function createConfig(options?: ConfigOptions): Linter.Config[];
declare const config: Linter.Config[];
export default config;
