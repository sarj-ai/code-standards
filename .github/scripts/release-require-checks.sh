#!/usr/bin/env bash
set -euo pipefail

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
    run="$(jq -c --arg sha "$TARGET_SHA" --arg repo "$GITHUB_REPOSITORY" \
      '[.workflow_runs[] | select(.head_sha == $sha and .event == "push" and .head_repository.full_name == $repo)] | first // empty' \
      <<<"$response")"
    if [[ -z "$run" ]]; then
      echo "waiting for $expected_name push run at $TARGET_SHA"
      sleep 15
      continue
    fi
    conclusion="$(jq -r '.conclusion // empty' <<<"$run")"
    if [[ "$conclusion" == success ]]; then
      echo "$expected_name succeeded for $TARGET_SHA"
      break
    fi
    if [[ -n "$conclusion" ]]; then
      echo "::error::$expected_name concluded $conclusion for $TARGET_SHA"
      exit 1
    fi
    # GitHub can finish every job successfully while leaving the
    # outer workflow-run record indefinitely in_progress. Derive the
    # same terminal result from the exact run's jobs so publishing is
    # not coupled to that eventual-consistency finalizer.
    run_id="$(jq -r '.id' <<<"$run")"
    jobs="$(gh api --method GET \
      "repos/$GITHUB_REPOSITORY/actions/runs/$run_id/jobs" \
      -f per_page=100)"
    failed_jobs="$(jq '[.jobs[] | select(.status == "completed" and .conclusion != "success" and .conclusion != "skipped" and .conclusion != "neutral")] | length' <<<"$jobs")"
    pending_jobs="$(jq '[.jobs[] | select(.status != "completed")] | length' <<<"$jobs")"
    successful_jobs="$(jq '[.jobs[] | select(.conclusion == "success")] | length' <<<"$jobs")"
    if ((failed_jobs > 0)); then
      jq -r '.jobs[] | select(.status == "completed" and .conclusion != "success" and .conclusion != "skipped" and .conclusion != "neutral") | "::error::\(.name) concluded \(.conclusion)"' <<<"$jobs"
      exit 1
    fi
    # CI's terminal job depends on the entire graph. A routing-only
    # jobs response must never count as completed validation.
    terminal_complete=true
    if [[ "$workflow" == ci.yml ]]; then
      terminal_complete="$(jq 'any(.jobs[]; .name == "CI complete" and .status == "completed" and .conclusion == "success")' <<<"$jobs")"
    fi
    if [[ "$terminal_complete" == true ]] && ((pending_jobs == 0 && successful_jobs > 0)); then
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
