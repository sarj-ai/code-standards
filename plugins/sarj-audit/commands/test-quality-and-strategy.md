Audit the codebase for common testing anti-patterns that create brittle, incomplete, or low-value tests. The focus is on improving test reliability and maintainability by preferring high-fidelity test doubles and sound structure over excessive mocking and implementation-detail testing.

## Test Quality and Strategy

A codebase has a strong test strategy when:
- Tests are reliable and only fail when there is a genuine regression.
- Test setup is realistic, using high-fidelity fakes or real services in containers (databases, external APIs) instead of brittle mocks.
- Code is structured for testability using dependency injection, isolating business logic from external services and frameworks.
- Test coverage is intentional, focusing on critical paths, business logic, and public APIs, rather than private implementation details.
- Tests are self-documenting, clearly expressing the behavior under test without requiring complex setup or comments.

A codebase has a **weak** test strategy when:
- It relies heavily on `unittest.mock.AsyncMock` or `MagicMock` to fake complex objects like database stores, leading to tests that pass even when the underlying code is broken.
- Application code is tightly coupled to global settings or concrete implementations, making it difficult to test in isolation.
- Tests are skipped (`@pytest.mark.skip`, `it.skip`) without a reason or a ticket to track re-enabling them.
- Tests target private methods, making them brittle and resistant to refactoring.
- Test coverage is superficial, with missing tests for new features, bug fixes, or complex logic.

## Phase 0: Discover project structure

Before spawning audit agents, run a single discovery step:

1.  **Detect project type and languages** — Identify project structure (monorepo vs. single package) and primary languages (Python, TypeScript).
2.  **Find all source and test roots** — Locate conventional source directories (`src/`, `lib/`, `app/`) and corresponding test directories (`tests/`, `__tests__/`).
3.  **Map source files to test files** — Establish a baseline mapping between application source files (e.g., `app/services/user_service.py`) and their corresponding test files (e.g., `tests/services/test_user_service.py`).
4.  **Partition into 2–10 agents** — Create agents based on source roots or logical application areas (e.g., `webserver`, `agent`, `worker`).

Output the discovered structure before proceeding.

## Phase 1: Audit (parallel agents)

Spawn the agents determined in Phase 0. Each agent must inspect its assigned scope for the following anti-patterns:

1.  **Over-reliance on Low-Fidelity Mocks** — Flag widespread use of `unittest.mock.Mock`, `MagicMock`, or `AsyncMock` for complex components like data stores or service clients. These mocks often hide real integration bugs. The presence of `noqa: TID251` is a strong indicator of this pattern.
2.  **Poor Dependency Injection** — Identify application modules that import and use global settings objects directly (e.g., `from app.config import settings`) instead of receiving dependencies via constructors or function arguments. This makes testing difficult. [2, 5, 6, 7, 9]
3.  **Testing Private Implementation Details** — Detect tests that call private methods or access private attributes (e.g., `_some_method`) of the class under test. This leads to brittle tests that break on refactoring. (`SLF001` is `private-member-access`, but it is commonly **per-file-ignored in test directories** — the exact files this check targets — so grep for `._` access on the unit-under-test rather than relying on the lint signal.) [1]
4.  **Skipped Tests** — Find all instances of skipped tests, such as `@pytest.mark.skip` (especially without a `reason`), `it.skip`, `test.skip`, `xit`, or `xdescribe`. These represent dead code in the test suite. Detect by **grepping** for `@pytest.mark.skip`/`.skip(`/`.only(` — there is **no** ruff rule for skipped tests (`PT022` is `pytest-useless-yield-fixture`, unrelated). For the TS side the runner is **vitest** (not jest): use `eslint-plugin-vitest`'s `no-disabled-tests`/`no-focused-tests`, or grep. [3, 8, 14, 16]
5.  **Brittle Mock Patch Paths** — Locate uses of `unittest.mock.patch` with string paths. These are highly susceptible to breaking silently during refactoring. The path should target where the object is *used*, not where it is defined. [18, 25]
6.  **Missing or Incomplete Test Coverage** — Heuristically identify source files that have been modified in recent history but their corresponding test files have not. Also, flag test files with a low assertion-to-code ratio.
7.  **Vacuous or Obsolete Tests** — Report tests that contain no assertions (`assert`, `expect`) or that test trivial logic (e.g., instantiating a blank `FastAPI()` app instead of the real application). Also, flag tests that have been commented out entirely.

## Phase 2: Compile findings

After all agents report back, compile a single summary table with columns:

| File | Lines | Issue | Severity | Suggested Fix |
|------|-------|-------|----------|---------------|

Group the summary into:
- **High severity** — Widespread use of low-fidelity mocks; critical business logic with no tests.
- **Medium severity** — Poor dependency injection; testing private implementation details; skipped tests.
- **Low severity** — Minor coverage gaps; vacuous tests; brittle mock paths.

Print the total count of violations found, broken down by severity and by source root.

## Phase 3: Generate fix plan

For each high- and medium-severity violation, output a concrete remediation plan:

-   **For Over-reliance on Mocks**: Propose replacing `AsyncMock` with a high-fidelity fake or a real database fixture. Provide an example: "In `test_user_creation.py`, replace `mock_user_store = AsyncMock()` with the `psql_user_store` fixture and adapt the test to use real store methods."
-   **For Poor Dependency Injection**: Propose refactoring to inject the dependency. Example: "In `reconcile.ts`, modify the `ReconcileService` constructor to accept an `attioClient` instead of importing it globally."
-   **For Testing Private Methods**: Recommend refactoring the test to only call the public API and assert on the observable outcome.
-   **For Skipped Tests**: Recommend either deleting the test if it's obsolete or creating a ticket to fix and re-enable it, removing the skip.

Do NOT automatically implement fixes. Present the plan for review.
