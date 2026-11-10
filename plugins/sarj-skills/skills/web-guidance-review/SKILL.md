---
name: web-guidance-review
description: Review browser-facing HTML, CSS and JavaScript against the audited modern web guidance. Use for web UI, accessibility, form, rendering, browser security or interaction changes; exclude backend-only changes and unrequested feature migrations.
---

Select the entries relevant to the changed behavior in the [source audit](../../../../docs/audits/modern-web-guidance.json). Each document has an assessment; each source block, including code examples, has a task ID and pinned line range. The [review policy](references/review-policy.md) explains the outcomes and compatibility exceptions. Read the relevant original sections, rather than loading the whole catalog.

Prefer existing project primitives and the shipped Standards checks. The managed Oxlint preset checks intrinsic JSX accessibility and selected form/resource/origin defects; the TypeScript capability also runs the managed Stylelint preset on selected CSS sources. A lint pass only establishes the documented detector boundary. Review custom components, referenced callbacks, HTML templates and runtime-generated content explicitly.

For applicable guidance outside those boundaries, verify the user-visible behavior: keyboard and focus movement, accessible names and announcements, text enlargement and forced colors, IME and clipboard input, reduced motion, async cancellation, request behavior and unsupported-browser fallbacks. Use the repository's supported-browser policy. Keep optional visual patterns, new browser APIs, passkeys, PWA, AI, WebMCP and extension features conditional on the requested product behavior.

Validate performance choices with the affected page and realistic content; a guide's numeric preload budget is a starting point, not a universal source-code limit. Validate security at the actual trust boundary, including server verification; a client guard or newly named API does not establish authorization.

For extension work, check the current Chrome API and store documentation before using the pinned examples. The audit records corrections to permission, icon, CSP and message-listener claims. Preserve least privilege and verify the packaged extension's behavior. Do not impose extension-only requirements on ordinary websites.

Report which checks ran, the relevant manual/browser evidence and any remaining gaps. Preserve the user's task and repository policy when guidance conflicts; do not rewrite working framework components or add a feature solely to satisfy an example.
