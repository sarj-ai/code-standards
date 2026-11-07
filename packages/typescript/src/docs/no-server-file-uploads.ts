/** @fileoverview no-server-file-uploads — the documentation and executable examples of `@sarj/no-server-file-uploads`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_SERVER_FILE_UPLOADS_DOCUMENTATION = {
  defaultLevel: "error",
  summary: "Keep native File handling outside explicit server boundaries.",
  rationale: "Accepting uploaded files routes their bytes through application workers, consuming connections, memory or temporary disk. Direct signed-URL uploads keep that transfer in object storage.",
  remediation: "Issue an authorized, short-lived signed URL; upload the browser File directly to storage, then submit its object key and metadata. Use Blob for server-generated binary content.",
  category: "architecture",
  limitations: [
    "Checks native File references in use-server modules/functions, server-only modules, and modules importing runtime Next.js server or Hono server constructors. Explicit use-client modules keep browser File access. Filenames and variable names do not establish a server boundary.",
    "Recognizes unshadowed File/globalThis.File and named or namespace File imports from node:buffer or buffer. Local definitions and unrelated File imports are excluded. Capturing the native constructor is reported at the capture; arbitrary re-exports and dynamic loaders are not resolved.",
    "Does not ban FormData, Blob, string-only forms, local file inputs or browser previews. The separate LIB120 dependency policy covers dedicated server multipart-upload libraries.",
    "This is an architectural restriction on native File use in known server boundaries, including local File construction. It cannot prove that a URL is signed, detect every raw-byte upload or enforce object ownership, expiration, size, checksum and post-upload validation.",
    "No automatic rewrite is offered because storage authorization and completion validation require application-specific logic.",
  ],
  references: [
    "https://developer.mozilla.org/en-US/docs/Web/API/File",
    "https://hono.dev/examples/file-upload",
    "https://docs.cloud.google.com/storage/docs/access-control/signed-urls",
  ],
  examples: [
    {
      id: "browser-signed-url",
      scenarioId: "direct-upload",
      title: "Send the browser File directly to storage",
      outcome: "no-match",
      files: [{ path: "app/upload.ts", source: "'use client'; export async function upload(file: File, signedUrl: string) { await fetch(signedUrl, { method: 'PUT', body: file, signal: AbortSignal.timeout(60000) }); }" }],
      focusPath: "app/upload.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "server-file-parameter",
      scenarioId: "direct-upload",
      title: "Accept an object key instead of file bytes",
      outcome: "match",
      files: [{ path: "app/actions.ts", source: "'use server'; export async function upload(file: File) { return file.name; }" }],
      focusPath: "app/actions.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "hono-file-validation",
      scenarioId: "handler-metadata",
      title: "Do not receive a file through a Hono route",
      outcome: "match",
      files: [{ path: "src/server.ts", source: "import { Hono } from 'hono'; const app = new Hono(); app.post('/upload', async (c) => { const body = await c.req.parseBody(); return c.json({ uploaded: body.file instanceof File }); });" }],
      focusPath: "src/server.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "server-object-metadata",
      scenarioId: "handler-metadata",
      title: "Finalize a previously authorized upload",
      outcome: "no-match",
      files: [{ path: "app/actions.ts", source: "'use server'; export async function complete(objectKey: string) { return validateUploadedObject(objectKey); }" }],
      focusPath: "app/actions.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
