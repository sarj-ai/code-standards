# Testing Strategy & Modernization Audit

Audit the test suite for fidelity and architectural quality, and evaluate the codebase for opportunities to replace complex, hand-rolled code with battle-tested third-party libraries.

> [!NOTE]
> This audit evaluates test design strategy and library adoption requiring high-level human/AI judgment.
> Deterministic AST test rules (such as `no_sleep_in_test_body`, `tautological_mock_assertion`, `zero_assertion_test`, `duplicate_test_body`, or `no_raw_sql_in_tests`) are enforced by `@sarj/eslint-plugin` and `sarj-python-lint`. Do **not** re-audit deterministic lint rules.

---

## What this audits

### 1. High-Fidelity Test Strategy & Architecture
- **Over-Mocking & Low-Fidelity Mocks**: Excessive reliance on `unittest.mock.MagicMock` or `AsyncMock` to fake complex components like data stores or HTTP clients, leading to tests that pass against invalid contracts.
- **Testing Implementation Details**: Tests binding to private methods or internal state variables rather than asserting observable outcomes on public interface boundaries, making code refactoring brittle.
- **Missing Integration Boundaries**: Test suites lacking real database container fixtures (`testcontainers`, Postgres/SQLite test DBs) or high-fidelity in-memory fakes for critical data access layers.

### 2. Third-Party Library Adoption & Codebase Modernization
- **Hand-Rolled Infrastructure Logic**: Custom implementations of complex concurrency patterns (semaphores, batching, rate-limiting, retry with exponential backoff) that should be replaced by mature packages (`p-limit`, `p-retry`, `tenacity`).
- **Hand-Rolled Domain & Parsing Logic**: Hand-rolled date/time calculations, CSV parsing, URL manipulation, binary encoding, or crypto operations that introduce edge-case bugs and should use battle-tested libraries (`date-fns`, `papaparse`, `validator`, `nanoid`).
- **Unnecessary Code Bloat**: Hand-rolled helpers that increase code volume by 50%+ compared to standard library or well-maintained package calls.

---

## Phase 0: Discover project structure

Run the shared **[stack-detection](./stack-detection.md)** pass first.

Inventory existing dependencies (`package.json`, `pyproject.toml`) and test framework setups (`vitest`, `pytest`) to avoid recommending libraries that are already installed or incompatible with target runtimes (Node, Edge, Browser, Python).

---

## Phase 1: Audit (parallel agents)

Spawn 2 parallel audit agents:

### Agent 1: Test Strategy & Fidelity Audit
- Audit test suites for `AsyncMock`/`MagicMock` over-use on data stores and complex domain services.
- Identify tests asserting on private/internal class methods instead of public contract outputs.
- Evaluate test double fidelity (fakes vs mocks vs real DB fixtures).

### Agent 2: Library Adoption & Modernization Audit
- Search for hand-rolled async concurrency control (batching, throttling, retries).
- Search for custom date/time parsing, string slugification, CSV processing, or URL manipulation.
- Estimate line reduction and verify runtime compatibility for proposed package replacements.

---

## Phase 2: Compile findings

Compile a single summary table:

| Focus Area | File & Lines | Current Approach | Recommendation | Impact | Line / Maintenance Reduction |
|------------|--------------|------------------|----------------|--------|------------------------------|

Sort by impact (**High** > **Medium** > **Low**), then by file path.

Group into:
- **High Impact**: Replacing brittle mocks on core data stores with high-fidelity fakes or test DB fixtures; replacing fragile custom retry/concurrency code with standard libraries.
- **Medium Impact**: Refactoring tests from private implementation details to public contracts; adopting standard packages for date/formatting/parsing logic.
- **Low Impact / Future**: Minor utility library consolidations.

---

## Phase 3: Generate recommendations & refactoring plan

For each High and Medium finding:
1. Provide a concrete example of replacing low-fidelity `AsyncMock` with a real store fixture or fake.
2. Show before-and-after snippets for hand-rolled logic vs library adoption, noting line count savings and bundle/runtime impact.

Do NOT automatically apply changes. Present recommendations for review.
