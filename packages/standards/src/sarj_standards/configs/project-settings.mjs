// eslint-disable-next-line @sarj/prefer-node-fs-promises -- This short-lived adapter performs a bounded synchronous scan and then exits.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { createRequire } from "node:module";
import { projectConfiguration } from "./project-configuration.mjs";

const FRAMEWORK_CAPABILITIES = Object.freeze([
  ["ssr", ["nextjs", "tanstack-start", "remix", "gatsby"]],
  ["server-actions", ["nextjs", "tanstack-start", "remix"]],
  ["client-only", ["vite", "cra", "gatsby", "react-native", "expo"]],
]);
const FRAMEWORKS = [
  ["next", "nextjs"],
  ["@astrojs/react", "astro"],
  ["@tanstack/react-start", "tanstack-start"],
  ["@remix-run/react", "remix"],
  ["expo", "expo"],
  ["react-native", "react-native"],
  ["gatsby", "gatsby"],
  ["vite", "vite"],
  ["react-scripts", "cra"],
  ["preact", "preact"],
];
const PACKAGES = {
  react: [
    "react",
    "react-dom",
    "react-native",
    "expo",
    "next",
    "@astrojs/react",
    "@vitejs/plugin-react",
    "@vitejs/plugin-react-swc",
  ],
  ssr: [
    "@react-router/cloudflare",
    "@react-router/node",
    "@react-router/serve",
    "vike",
    "vite-plugin-ssr",
  ],
  preact: ["preact"],
  "react-native": ["react-native", "expo"],
  expo: ["expo"],
  "react-compiler": ["react-compiler-runtime"],
  "base-ui": ["@base-ui/react", "@base-ui-components/react"],
  "radix-ui": ["radix-ui"],
  "react-aria": ["react-aria-components"],
  "tanstack-query": ["@tanstack/react-query"],
  "tanstack-form": ["@tanstack/react-form"],
  "tanstack-table": ["@tanstack/react-table"],
  "tanstack-virtual": ["@tanstack/react-virtual"],
  "styled-components": ["styled-components"],
  tailwind: ["tailwindcss"],
  valtio: ["valtio"],
  zustand: ["zustand"],
  three: ["three", "@react-three/fiber"],
  r3f: ["@react-three/fiber"],
  "react-router": ["react-router", "react-router-dom"],
  "react-router-framework": ["@react-router/dev"],
  remotion: ["remotion", "@remotion/player"],
  zod: ["zod"],
  mobx: ["mobx", "mobx-react", "mobx-react-lite", "mobx-state-tree", "mobx-react-observer"],
  "mobx-react": ["mobx-react"],
  "mobx-react-lite": ["mobx-react-lite"],
  "mobx-react-binding": ["mobx-react", "mobx-react-lite"],
  "mobx-state-tree": ["mobx-state-tree"],
  "mobx-react-observer": ["mobx-react-observer"],
  reanimated: ["react-native-reanimated"],
  typescript: ["typescript"],
  i18n: ["i18next", "react-i18next", "next-intl", "react-intl", "@lingui/core"],
};
const VERSION_LADDERS = [
  ["react", "react", 17, 30],
  ["nextjs", "next", 15, 16],
  ["preact", "preact", 10, 20],
  ["r3f", "@react-three/fiber", 3, 10],
  ["remotion", "remotion", 4, 30],
  ["valtio", "valtio", 1, 10],
  ["zustand", "zustand", 1, 5],
  ["mobx", "mobx", 4, 6],
];
const VERSION_THRESHOLDS = [
  ["react:19.2", "react", 19, 2],
  ["expo:54", "expo", 54, 0],
  ["styled-components:6", "styled-components", 6, 0],
  ["zod:4", "zod", 4, 0],
  ["reanimated:4", "react-native-reanimated", 4, 0],
  ["tailwind:3.4", "tailwindcss", 3, 4],
  ["tailwind:4", "tailwindcss", 4, 0],
  ["mobx:6.10", "mobx", 6, 10],
  ["mobx-react-observer-memo-guard", "mobx-react", 7, 3],
  ["mobx-react-lite-observer-memo-guard", "mobx-react-lite", 3, 3],
];
const ROUTER_THRESHOLDS = [
  [6, 4],
  [6, 7],
  [6, 9],
  [6, 19],
  [7, 0],
  [7, 8],
  [7, 9],
  [7, 10],
  [7, 15],
  [8, 0],
];

function version(dependencies, name) {
  return String(dependencies[name] ?? "")
    .match(/(\d+)\.(\d+)/)
    ?.slice(1)
    .map(Number);
}

function atLeast(dependencies, name, major, minor) {
  const detected = version(dependencies, name);
  if (!detected) return false;
  if (detected[0] > major) return true;
  return detected[0] === major && detected[1] >= minor;
}

export function projectSettings(root, core, repositoryRoot, parse) {
  const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
  const dependencies = {
    ...pkg.dependencies,
    ...pkg.devDependencies,
    ...pkg.peerDependencies,
    ...pkg.optionalDependencies,
  };
  resolveReactRuntime(root, dependencies);
  resolveCapabilityDependencies(root, dependencies);
  const framework = FRAMEWORKS.find(([name]) => dependencies[name])?.[1] ?? "unknown";
  const packages = Object.entries(PACKAGES)
    .filter(([, names]) => names.some((name) => dependencies[name]))
    .map(([capability]) => capability);
  const nativeAware =
    // eslint-disable-next-line @sarj/no-runtime-typeof -- The raw package manifest allows a string entry point or an object platform map.
    typeof pkg["react-native"] === "string" ||
    Object.keys(dependencies).some(core.isReactNativeDependencyName);
  const capabilities = new Set([
    framework,
    ...packages,
    ...frameworkCapabilities(framework),
    ...versionCapabilities(dependencies),
    ...extraCapabilities(dependencies, root),
  ]);
  if (nativeAware) capabilities.add("react-native");
  const configuration = projectConfiguration(root, repositoryRoot, parse);
  if (configuration.compiler) capabilities.add("react-compiler");
  if (configuration.staticExport && framework === "nextjs") {
    capabilities.add("nextjs:static-export");
    capabilities.delete("server-actions");
  }
  return {
    framework,
    rootDirectory: root,
    capabilities: [...capabilities].sort(),
    portedRuleMode: "curated",
    compilerChecks: configuration.compiler || configuration.compilerLint,
  };
}

function versionCapabilities(dependencies) {
  const thresholds = VERSION_THRESHOLDS.filter(([, name, major, minor]) =>
    atLeast(dependencies, name, major, minor),
  ).map(([key]) => key);
  const router = dependencies["react-router"] ? "react-router" : "react-router-dom";
  const routerCapabilities = ROUTER_THRESHOLDS.filter(([major, minor]) =>
    atLeast(dependencies, router, major, minor),
  ).map(([major, minor]) => `react-router:${minor ? `${major}.${minor}` : major}`);
  const threeRelease = version(dependencies, "three")?.[1] ?? 0;
  const threeCapabilities = Array.from(
    { length: Math.max(0, Math.min(threeRelease, 250) - 144) },
    (_, offset) => `three:${145 + offset}`,
  );
  return [
    ...ladderCapabilities(dependencies),
    ...thresholds,
    ...routerCapabilities,
    ...threeCapabilities,
  ];
}

function ladderCapabilities(dependencies) {
  return VERSION_LADDERS.flatMap(([name, packageName, first, last]) => {
    const major = version(dependencies, packageName)?.[0] ?? 0;
    const count = Math.max(0, Math.min(major, last) - first + 1);
    return Array.from({ length: count }, (_, offset) => `${name}:${first + offset}`);
  });
}

function frameworkCapabilities(framework) {
  return FRAMEWORK_CAPABILITIES
    .filter(([, frameworks]) => frameworks.includes(framework))
    .map(([capability]) => capability);
}

function extraCapabilities(dependencies, root) {
  const enabled = [
    ["pure-preact", Boolean(dependencies.preact) && !dependencies.react],
    ["radix-ui", Object.keys(dependencies).some((name) => name.startsWith("@radix-ui/"))],
    ["shadcn", existsSync(join(root, "components.json"))],
    [
      "mobx-react-binding-observer-memo-guard",
      atLeast(dependencies, "mobx-react", 7, 3) || atLeast(dependencies, "mobx-react-lite", 3, 3),
    ],
  ];
  return enabled.filter(([, present]) => present).map(([capability]) => capability);
}

function resolveReactRuntime(root, dependencies) {
  if (dependencies.react || dependencies.preact) return;
  if (!PACKAGES.react.some((name) => dependencies[name])) return;
  try {
    const require = createRequire(join(root, "package.json"));
    dependencies.react = JSON.parse(
      readFileSync(require.resolve("react/package.json"), "utf8"),
    ).version;
  } catch (cause) {
    throw new Error(
      "React Doctor could not resolve the inherited React runtime; refusing to disable capability-dependent checks",
      { cause },
    );
  }
}

function resolveCapabilityDependencies(root, dependencies) {
  const require = createRequire(join(root, "package.json"));
  const names = new Set([
    ...VERSION_LADDERS.map(([, name]) => name),
    ...VERSION_THRESHOLDS.map(([, name]) => name),
    "react-router",
    "react-router-dom",
  ]);
  for (const name of names) {
    const declared = String(dependencies[name] ?? "");
    if (/^(?:catalog:|workspace:|npm:)/.test(declared)) {
      try {
        const installed = JSON.parse(readFileSync(require.resolve(`${name}/package.json`), "utf8"));
        dependencies[name] = installed.version;
      } catch (cause) {
        throw new Error(
          `React Doctor capability requires a resolved version for ${name}; ${declared} could not be resolved`,
          { cause },
        );
      }
    }
  }
}
