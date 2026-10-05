import { cp } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
for (const family of ["shadcn", "better-tailwindcss", "tailwind-csstree"])
  await cp(
    resolve(root, "vendor", family),
    resolve(root, "dist/upstream", family),
    { recursive: true },
  );
