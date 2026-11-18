#!/usr/bin/env bash
set -euo pipefail

case "$TARGET_BRANCH" in
  main | maintenance/standards-8.101 | maintenance/standards-8.129 | maintenance/standards-8.208) ;;
  *)
    echo "::error::publication branch is not allowed"
    exit 1
    ;;
esac

deadline=$((SECONDS + 2700))
for specification in \
  'repo-ci.yml|release-ready' \
  'private-refs.yml|private references' \
  'ci.yml|CI'; do
  IFS='|' read -r workflow expected_name <<<"$specification"
  while ((SECONDS < deadline)); do
    response="$(gh api --method GET \
      "repos/$GITHUB_REPOSITORY/actions/workflows/$workflow/runs" \
      -f head_sha="$TARGET_SHA" -f event=push -f per_page=10)"
    run="$(jq -c --arg sha "$TARGET_SHA" --arg repo "$GITHUB_REPOSITORY" --arg branch "$TARGET_BRANCH" --arg path ".github/workflows/$workflow" \
      '[.workflow_runs[] | select(.head_sha == $sha and .head_branch == $branch and .event == "push" and .path == $path and .head_repository.full_name == $repo)] | max_by(.id) // empty' \
      <<<"$response")"
    if [[ -z "$run" ]]; then
      echo "waiting for $expected_name push run at $TARGET_SHA"
      sleep 15
      continue
    fi
    conclusion="$(jq -r '.conclusion // empty' <<<"$run")"
    if [[ "$workflow" != ci.yml && "$conclusion" == success ]]; then
      echo "$expected_name succeeded for $TARGET_SHA"
      break
    fi
    if [[ -n "$conclusion" && "$conclusion" != success && ! ("$workflow" == ci.yml && "$conclusion" == failure) ]]; then
      echo "::error::$expected_name concluded $conclusion for $TARGET_SHA"
      exit 1
    fi
    # GitHub can finish every job successfully while leaving the
    # outer workflow-run record indefinitely in_progress. Derive the
    # same terminal result from the exact run's jobs so publishing is
    # not coupled to that eventual-consistency finalizer.
    run_id="$(jq -er '.id | select(type == "number" and . > 0 and floor == .)' <<<"$run")"
    attempt="$(jq -er '.run_attempt | select(type == "number" and . > 0 and floor == .)' <<<"$run")"
    jobs="$(gh api --method GET \
      "repos/$GITHUB_REPOSITORY/actions/runs/$run_id/attempts/$attempt/jobs" \
      -f per_page=100)"
    jq -e '.total_count == (.jobs | length)' <<<"$jobs" >/dev/null
    if [[ "$workflow" == ci.yml ]]; then
      qualification="$(jq -ec '[.jobs[] | select(.name == "CI packages")] as $package | (if ($package | length) == 0 then [.jobs[] | select(.name == "CI complete")] else $package end) | if length == 0 then {} elif length == 1 then .[0] else error("ambiguous CI qualification") end' <<<"$jobs")"
      qualifier="$(jq -r '.name // empty' <<<"$qualification")"
      result="$(jq -r 'if .status == "completed" then .conclusion else "" end' <<<"$qualification")"
      if [[ "$result" == success ]]; then
        latest="$(gh api --method GET "repos/$GITHUB_REPOSITORY/actions/runs/$run_id")"
        jq -e --arg sha "$TARGET_SHA" --arg branch "$TARGET_BRANCH" --arg repo "$GITHUB_REPOSITORY" --arg qualifier "$qualifier" --argjson run_id "$run_id" --argjson attempt "$attempt" 'has("conclusion") and .id == $run_id and .run_attempt == $attempt and .head_sha == $sha and .head_branch == $branch and .event == "push" and .path == ".github/workflows/ci.yml" and .head_repository.full_name == $repo and (.conclusion == null or .conclusion == "success" or (.conclusion == "failure" and $qualifier == "CI packages"))' <<<"$latest" >/dev/null
        echo "$expected_name jobs succeeded for $TARGET_SHA (run $run_id, attempt $attempt, $qualifier)"
        break
      fi
      if [[ -n "$result" || -n "$conclusion" ]]; then
        echo "::error::CI package qualification did not succeed for $TARGET_SHA"
        exit 1
      fi
      echo "waiting for package qualification at $TARGET_SHA"
      sleep 15
      continue
    fi
    failed_jobs="$(jq '[.jobs[] | select(.status == "completed" and .conclusion != "success" and .conclusion != "skipped" and .conclusion != "neutral")] | length' <<<"$jobs")"
    pending_jobs="$(jq '[.jobs[] | select(.status != "completed")] | length' <<<"$jobs")"
    successful_jobs="$(jq '[.jobs[] | select(.conclusion == "success")] | length' <<<"$jobs")"
    if ((failed_jobs > 0)); then
      jq -r '.jobs[] | select(.status == "completed" and .conclusion != "success" and .conclusion != "skipped" and .conclusion != "neutral") | "::error::\(.name) concluded \(.conclusion)"' <<<"$jobs"
      exit 1
    fi
    if ((pending_jobs == 0 && successful_jobs > 0)); then
      echo "$expected_name jobs succeeded for $TARGET_SHA; outer run finalization is still pending"
      break
    fi
    echo "waiting for $expected_name to complete at $TARGET_SHA"
    sleep 15
  done
  if ((SECONDS >= deadline)); then
    echo "::error::timed out waiting for $expected_name at $TARGET_SHA"
    exit 1
  fi
done
