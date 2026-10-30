import type { Reporter, TestCase, Vitest } from "vitest/node";

const PREVIEW_CHARACTER_LIMIT = 4096;

export class FirstFailureReporter implements Reporter {
  #vitest: Vitest | undefined;
  #previewed = false;

  onInit(vitest: Vitest): void {
    this.#vitest = vitest;
  }

  onTestRunStart(): void {
    this.#previewed = false;
  }

  onTestCaseResult(test: TestCase): void {
    const result = test.result();
    if (this.#previewed || result.state !== "failed") return;
    this.#previewed = true;
    const error = result.errors[0];
    const preview = [
      "First failed test (preview; complete details remain in the final report):",
      `${test.module.relativeModuleId} > ${test.fullName}`,
      error?.stack ?? error?.message ?? "No serialized error detail.",
    ].join("\n");
    this.#vitest?.logger.error(`\n${preview.slice(0, PREVIEW_CHARACTER_LIMIT)}\n[End of first failure preview]\n`);
  }
}
