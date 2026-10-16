import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { parseReference } from "./parse-reference";

export interface CliOption {
  kind: "option" | "positional";
  names: string[];
  metavar: string | null;
  summary: string;
  choices: string[];
  required: boolean;
  repeatable: boolean;
}

export interface CliCommand {
  name: string;
  path: string[];
  usage: string;
  summary: string;
  options: CliOption[];
  commands: CliCommand[];
}

export interface CliReference {
  schemaVersion: 1;
  version: string;
  program: string;
  summary: string;
  epilog: string | null;
  globalOptions: CliOption[];
  commands: CliCommand[];
  launcher: {
    install: string;
    runLatest: string;
  };
}

const referencePath = resolve(
  process.cwd(),
  "../../packages/standards/src/sarj_standards/configs/cli-reference.v1.json",
);

async function loadReference(): Promise<CliReference> {
  let source: string;
  try {
    source = await readFile(referencePath, "utf8");
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      throw new Error(
        `Generated CLI reference is missing at ${referencePath}. Generate it before building apps/docs.`,
        {
          cause: error,
        },
      );
    }
    throw error;
  }
  let value: unknown;
  try {
    value = JSON.parse(source) as unknown;
  } catch (error) {
    throw new Error(
      `Generated CLI reference is not valid JSON at ${referencePath}.`,
      { cause: error },
    );
  }
  return parseReference(value);
}

export const cliReference = await loadReference();

export function invocation(command: CliCommand): string {
  return [cliReference.program, ...command.path].join(" ");
}

export function flattenCommands(
  commands: CliCommand[] = cliReference.commands,
): CliCommand[] {
  return commands.flatMap((command) => [
    command,
    ...flattenCommands(command.commands),
  ]);
}

export function commandAnchor(command: CliCommand): string {
  return command.path.join("-");
}

export function optionLabel(option: CliOption): string {
  if (option.kind === "positional")
    return option.metavar ?? option.names.at(0) ?? "";
  return `${option.names.join(", ")}${option.metavar ? ` ${option.metavar}` : ""}`;
}
