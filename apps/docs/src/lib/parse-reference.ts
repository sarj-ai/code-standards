import type { CliReference, CliOption, CliCommand } from "./cli.ts";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireText(
  value: unknown,
  label: string,
  allowEmpty = false,
): asserts value is string {
  if (typeof value !== "string" || (!allowEmpty && value["length"] === 0)) {
    throw new TypeError(
      `${label} must be ${allowEmpty ? "a string" : "a non-empty string"}.`,
    );
  }
}

function validateOption(
  value: unknown,
  label: string,
): asserts value is CliOption {
  if (!isRecord(value)) throw new TypeError(`${label} must be an object.`);
  if (value["kind"] !== "option" && value["kind"] !== "positional")
    throw new TypeError(`${label}.kind is invalid.`);
  if (
    !Array.isArray(value["names"]) ||
    !value["names"].every((name) => typeof name === "string")
  ) {
    throw new TypeError(`${label}.names must be a string array.`);
  }
  requireText(value["summary"], `${label}.summary`, true);
  if (value["metavar"] !== null && typeof value["metavar"] !== "string")
    throw new TypeError(`${label}.metavar is invalid.`);
  if (
    !Array.isArray(value["choices"]) ||
    !value["choices"].every((choice) => typeof choice === "string")
  ) {
    throw new TypeError(`${label}.choices must be a string array.`);
  }
  if (
    typeof value["required"] !== "boolean" ||
    typeof value["repeatable"] !== "boolean"
  ) {
    throw new TypeError(`${label} required and repeatable must be booleans.`);
  }
}

export function parseReference(value: unknown): CliReference {
  if (!isRecord(value) || value["schemaVersion"] !== 1)
    throw new TypeError("CLI reference must use schemaVersion 1.");
  requireText(value["version"], "CLI reference version");
  requireText(value["program"], "CLI reference program");
  requireText(value["summary"], "CLI reference summary");
  if (value["epilog"] !== null && typeof value["epilog"] !== "string")
    throw new TypeError("CLI reference epilog is invalid.");
  if (
    !Array.isArray(value["globalOptions"]) ||
    !Array.isArray(value["commands"])
  ) {
    throw new TypeError(
      "CLI reference globalOptions and commands must be arrays.",
    );
  }
  for (const [index, option] of value["globalOptions"].entries()) {
    validateOption(option, `globalOptions[${String(index)}]`);
  }
  for (const [index, command] of value["commands"].entries()) {
    validateCommand(command, `commands[${String(index)}]`);
  }
  if (!isRecord(value["launcher"]))
    throw new TypeError("CLI reference launcher must be an object.");
  requireText(value["launcher"]["install"], "CLI reference launcher install");
  requireText(
    value["launcher"]["runLatest"],
    "CLI reference launcher runLatest",
  );
  return value as unknown as CliReference;
}

function validateCommand(
  value: unknown,
  label: string,
): asserts value is CliCommand {
  if (!isRecord(value)) throw new TypeError(`${label} must be an object.`);
  requireText(value["name"], `${label}.name`);
  requireText(value["usage"], `${label}.usage`);
  requireText(value["summary"], `${label}.summary`, true);
  if (
    !Array.isArray(value["path"]) ||
    !value["path"].every((part) => typeof part === "string")
  ) {
    throw new TypeError(`${label}.path must be a string array.`);
  }
  if (!Array.isArray(value["options"]) || !Array.isArray(value["commands"])) {
    throw new TypeError(`${label} options and commands must be arrays.`);
  }
  for (const [index, option] of value["options"].entries()) {
    validateOption(option, `${label}.options[${String(index)}]`);
  }
  for (const [index, command] of value["commands"].entries()) {
    validateCommand(command, `${label}.commands[${String(index)}]`);
  }
}
