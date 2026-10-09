#!/usr/bin/env bash
set -e

npm install --ignore-scripts --no-audit --no-fund --save-dev typescript@7.0.2
mkdir -p smoke/src
cat >smoke/tsconfig.json <<'EOF'
{
  "extends": "../strict.json",
  "include": ["src/**/*"],
  "compilerOptions": {
    "noEmit": true,
    "outDir": "out"
  }
}
EOF
cat >smoke/src/index.ts <<'EOF'
export function add(a: number, b: number): number {
  return a + b;
}
EOF
cd smoke
../node_modules/.bin/tsc --noEmit -p tsconfig.json
