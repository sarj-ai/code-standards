# Comments and Self-Documenting Code

**Rule ID**: `SARJ-COMMENTS-01`
**Severity**: Error

## Motivation
Code should explain *what* and *how* by its structure and naming. Comments should only explain *why*. 
Superfluous, unhelpful, redundant, or restating-the-code comments create noise, drift from the actual implementation over time, and obscure real intent. 

## Violations
- **Restating the code**: `# increment i by 1`, `// return response`, `# function to handle submit`.
- **Commented-out code**: Any blocks of commented-out code should be removed. Source control handles history.
- **Trivial docstrings**: A docstring that just repeats the method or class name (e.g. `def get_user(): """Get user."""`).
- **Placeholder comments**: Auto-generated comments left untouched.

## Remediation
- Delete redundant comments.
- Rename variables or functions if the code is unclear.
- Move "why" explanations to comments if the rationale is non-obvious (e.g. referencing a specific business rule, workaround for a bug, etc.).

