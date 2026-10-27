import { z } from "zod";

const Schema = z.uuid();

export function isString(value: unknown): value is string {
  return Schema.safeParse(value).success;
}
