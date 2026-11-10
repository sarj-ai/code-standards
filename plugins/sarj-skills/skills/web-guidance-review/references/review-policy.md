# Modern web review policy

The audit pins GoogleChrome/modern-web-guidance at `4dd968349e54ca45a05dd5c818fb035c9054b022`. It includes every Markdown document and the tool policy, including the Chrome extension skill and references outside the main guide index. Tasks identify source blocks rather than pretending every paragraph is a distinct rule. Code examples have tasks too; headings and metadata remain reference tasks.

Use `review-standard` tasks as acceptance criteria when their feature is present. Their original source section supplies the detailed behavior; their document assessment records applicability and important limits. `feature-specific` tasks require that feature before they apply. `compatibility-policy` tasks require the project's actual runtime matrix and current authoritative compatibility evidence. `reference` tasks provide context. `rejected` tasks describe upstream/tool-specific or overly broad advice that is not a Sarj requirement. `partial-lint` tasks have a concrete, limited detector; their remaining behavior still needs review.

Do not turn tutorial recipes into universal requirements. In particular:

- Preserve deliberate dialog autofocus, Safari list-role workarounds, accessible custom controls, CSS and JavaScript fallbacks, and framework-managed DOM. Do not require positive or negative tabindex mechanically.
- Check focus restoration, roving focus, announcements, validation timing, IME composition, password-manager and OTP paste, keyboard alternatives to drag/swipe, and pending/error states through real interactions. Static attribute checks cannot establish these behaviors.
- Preserve user font preferences, text wrapping, forced colors and usable focus outlines. Plain nonzero pixel font sizes receive a CSS advisory; mixed-unit math, print typography and measured rendering require context.
- Respect reduced motion without globally setting every animation to 0.01ms. Keep content and completion logic usable when animations never start. Review repeated motion, pause controls and flash limits separately.
- Keep data minimization, consent, retention, third-party requests and client output safety explicit. Feature detection is not consent or authorization. Verify passkey challenges, RP IDs, origins and signatures on the server if passkeys are introduced.
- Do not require Origin, Temporal, built-in AI, native selects, new overlay APIs, install elements, HTML-in-canvas or WebMCP merely because a guide exists. Preserve the supported runtime policy and safe degradation.

Additional limits on the general guides:

- A build-time Tailwind CSS import is not a browser render-blocking import chain. Review the emitted CSS; do not ban all source imports or require one bundling recipe.
- Scope Clear-Site-Data to a deliberate clearing operation, such as logout or reset. Do not attach it to every response as a supposedly low-risk default. Review HSTS preload/includeSubDomains against the whole owned host inventory and redact security reports before enabling samples.
- Preserve security-driven no-store and sensitive-page cache policies. Performance guidance cannot choose the application's disclosure or authentication boundary.
- Do not hide merely offscreen content from assistive technology automatically. Hide inactive content when the interaction calls for it, and verify focus/read order.
- React JSX callbacks are not HTML inline script strings. Native controls can legitimately have custom keyboard behavior, and dynamic inline styles can carry measured positions or custom properties. Review the behavior rather than banning these syntax forms.

Corrections to the pinned Chrome extension advice:

- Promise-returning `runtime.onMessage` responses are a Chrome 148 rollout, with a DevTools-page exception. The source's Chrome 99 claim is not a valid minimum-version guard. The literal-true/sendResponse pattern remains a compatible option. [Chrome messaging](https://developer.chrome.com/docs/extensions/develop/concepts/messaging)
- `tabs` is one way to obtain sensitive tab properties. Matching host permissions or a valid activeTab grant can also provide access; requiring broad tabs/host permissions everywhere would weaken least privilege. Grants depend on invocation and navigation state. [Tabs](https://developer.chrome.com/docs/extensions/reference/api/tabs), [activeTab](https://developer.chrome.com/docs/extensions/develop/concepts/activeTab)
- Real packaged icon references matter, and multiple resolutions improve quality. Chrome supports raster formats besides PNG and selects suitable sizes; one separate PNG per size is not a universal functional requirement. [Manifest icons](https://developer.chrome.com/docs/extensions/reference/manifest/icons), [Action icons](https://developer.chrome.com/docs/extensions/reference/api/action)
- A Blob or srcdoc is not a general permission to bypass extension CSP safely. Use a deliberately sandboxed execution boundary, validate messages and keep the extension's privileges outside it. Verify the effective policy. [Extension CSP](https://developer.chrome.com/docs/extensions/reference/manifest/content-security-policy)
- Persist state that must survive a service-worker restart; transient variables are still valid within one event. Storage writes alone do not make a read/check/write sequence an atomic lock. Test concurrent capture/open requests and cleanup.

The source skill's requests to execute an unpinned latest CLI, change approval allowlists, cast unsupported attributes to any, or dictate final-answer headings are not adopted. Use pinned tooling, repository typing policy and the current user's authorization instead.
