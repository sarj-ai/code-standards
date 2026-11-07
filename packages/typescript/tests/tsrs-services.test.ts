import type { Symbol as TsSymbol } from "tsrs/sync";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Context } from "../src/types.js";
import { nativeTypes } from "../src/utils/checked-native-source.js";
import { tsrsServices, type TsrsFile } from "../src/utils/tsrs-services.js";
import { probe } from "./utils/_probe.js";

const CODE = "export const answer = 42;";

function typed<T>(name: string, evaluate: (context: Context) => T): T {
  return probe(CODE, evaluate, { filename: `/tmp/sarj-tsrs-services/${name}.ts` });
}

function services(context: Context) {
  const found = tsrsServices(context);
  if (found === null) throw new Error("tsrs services are unavailable");
  return found;
}

function requestTsrsRejectsWhileAlive(file: TsrsFile) {
  return nativeTypes(file).checker.getTypeOfSymbol({ id: 2 ** 30 } as unknown as TsSymbol);
}

describe("tsrsServices failures", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("turns tsrs off for the rest of the file after a rule error, reporting its stack, and only for that file", () => {
    const stderr = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    const results = typed("rule-error", (context) => [
      services(context).run(() => {
        throw new Error("rule bug");
      }),
      services(context).run(() => "typed"),
    ]);
    expect(results).toEqual([null, null]);
    expect(stderr).toHaveBeenCalledTimes(1);
    expect(String(stderr.mock.calls[0]?.[0])).toMatch(/^@sarj: tsrs request failed on \/tmp\/sarj-tsrs-services\/rule-error\.ts, .*for this file: Error: rule bug\n\s+at /u);
    expect(typed("after-rule-error", (context) => services(context).run(() => "typed"))).toBe("typed");
  });

  it("turns tsrs off for the rest of the file after a failed request, and only for that file", () => {
    const stderr = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    const results = typed("rejected", (context) => [
      services(context).run(requestTsrsRejectsWhileAlive),
      services(context).run(() => "typed"),
    ]);
    expect(results).toEqual([null, null]);
    expect(stderr).toHaveBeenCalledTimes(1);
    expect(String(stderr.mock.calls[0]?.[0])).toMatch(/^@sarj: tsrs request failed on \/tmp\/sarj-tsrs-services\/rejected\.ts, .*for this file: /u);
    expect(typed("after-rejected", (context) => services(context).run(() => "typed"))).toBe("typed");
  });
});
