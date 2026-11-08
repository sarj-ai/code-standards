#!/usr/bin/env bash
# Benchmark only. Released engine vs candidate builds on this tree, cache off,
# then optionally one candidate with a cold cache write and a read-only cached
# run. Every report must be byte-identical to the released engine's.
# env: BASE_VERSION, CANDIDATES ("name=sha ..."), CHECK_ARGS, CACHE_CANDIDATE
set -uo pipefail
out=$RUNNER_TEMP/ab
mkdir -p "$out"
export UV_PYTHON_DOWNLOADS_JSON_URL=https://raw.githubusercontent.com/astral-sh/uv/4ecd0eff2a81e3ffdcd7cfee10d08936e4747c17/crates/uv-python-managed/download-metadata.json
unset SARJ_STANDARDS_RESULT_CACHE SARJ_STANDARDS_RESULT_CACHE_WRITE
read -r -a check_args <<<"${CHECK_ARGS:-. --trust-repository-code --skip-python-type-check}"
log() { printf '%s\t%s\n' "$1" "$2" | tee -a "$out/summary.tsv"; }

git clone -q --filter=blob:none https://github.com/sarj-ai/code-standards "$RUNNER_TEMP/cs"
declare -A engines
engines[base]="--with code-standards==$BASE_VERSION"
for candidate in $CANDIDATES; do
  name=${candidate%%=*} sha=${candidate#*=}
  git -C "$RUNNER_TEMP/cs" checkout -q --force "$sha"
  for package in standards python sql iac contracts; do
    (cd "$RUNNER_TEMP/cs" && uvx --no-config uv@0.13.5 build --wheel --out-dir "$RUNNER_TEMP/wheels-$name" "packages/$package" >/dev/null) || exit 1
  done
  engines[$name]=$(for wheel in "$RUNNER_TEMP/wheels-$name"/*.whl; do printf -- '--with %s ' "$wheel"; done)
done

run() { # tag engine mode(off|write|read)
  local tag=$1 engine=$2 mode=$3 s
  read -r -a withs <<<"${engines[$engine]}"
  s=$(date +%s.%N)
  (
    case $mode in
      write) export SARJ_STANDARDS_RESULT_CACHE=$RUNNER_TEMP/cache SARJ_STANDARDS_RESULT_CACHE_WRITE=1 ;;
      read) export SARJ_STANDARDS_RESULT_CACHE=$RUNNER_TEMP/cache ;;
    esac
    SARJ_STANDARDS_BASE=$(git rev-parse HEAD^1) uv run --no-config --no-project --isolated --python 3.15.0 "${withs[@]}" \
      code-standards --root "$PWD" check "${check_args[@]}" --format json >"$out/$tag.json" 2>"$out/$tag.err"
  )
  log "$tag-exit" "$?"
  log "$tag-wall" "$(echo "$(date +%s.%N) - $s" | bc)"
  if [[ $tag != base-1 ]]; then
    if cmp -s "$out/base-1.json" "$out/$tag.json"; then log "base-1-vs-$tag" identical; else log "base-1-vs-$tag" DIFFERENT; fi
  fi
}

run base-1 base off
for candidate in $CANDIDATES; do run "${candidate%%=*}-1" "${candidate%%=*}" off; done
run base-2 base off
for candidate in $CANDIDATES; do run "${candidate%%=*}-2" "${candidate%%=*}" off; done
if [[ -n ${CACHE_CANDIDATE:-} ]]; then
  run "$CACHE_CANDIDATE-cold-write" "$CACHE_CANDIDATE" write
  run "$CACHE_CANDIDATE-cached-read" "$CACHE_CANDIDATE" read
  grep 'result cache' "$out/$CACHE_CANDIDATE-cached-read.err" | tee -a "$out/summary.tsv"
fi
