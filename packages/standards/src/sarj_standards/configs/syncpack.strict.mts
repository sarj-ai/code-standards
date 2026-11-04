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
    {
      label: "Standards root peers are exact tested pins while workspaces use compatible ranges",
      dependencies: [
        "@eslint/js",
        "eslint-plugin-perfectionist",
        "eslint-plugin-react-hooks",
        "eslint-plugin-simple-import-sort",
        "typescript-eslint",
      ],
      isIgnored: true,
    },
  ],
} satisfies RcFile);
