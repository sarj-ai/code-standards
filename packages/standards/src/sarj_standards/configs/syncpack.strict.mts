import type { RcFile } from "syncpack";

// Managed by code-standards. Keep repository-specific groups in .syncpackrc.ts.
export default Object.freeze({
  customTypes: {
    packageManager: {
      path: "packageManager",
      strategy: "name@version",
    },
  },
  versionGroups: [
    {
      label: "Root resolutions are hand-managed security floors",
      dependencyTypes: ["resolutions"],
      isIgnored: true,
    },
  ],
} satisfies RcFile);
