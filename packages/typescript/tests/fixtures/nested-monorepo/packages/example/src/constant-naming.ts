import { z } from "zod";

export const moduleMetadata = { stable: true };
export const MODULE_METADATA = { stable: true };
export const UserSchema = z.object({ id: z.string() });
export const USER_SCHEMA = z.object({ id: z.string() });
export const parseMetadata = (): boolean => true;
export const Route = { path: "/" };
export const metadata = { title: "Framework-owned export" };
