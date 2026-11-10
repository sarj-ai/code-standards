// vitest: shared-module-graph
import rule from "../../src/rules/no-message-origin-string-matching.js";
import { ruleTester } from "./_tester.js";

ruleTester().run("no-message-origin-string-matching", rule, {
  valid: [
    'window.addEventListener("message", event => { event = businessRecord; event.origin.includes("report"); });',
    'window.addEventListener("message", (event) => { if (event.origin === "https://trusted.example") accept(event.data); });',
    'window.addEventListener("message", (event) => { if (allowedOrigins.includes(event.origin)) accept(event.data); });',
    'window.addEventListener("message", (event) => { const url = new URL(event.origin); if (url.hostname === "trusted.example") accept(event.data); });',
    'window.addEventListener("message", (event) => { if (event.data.startsWith("prefix")) accept(event.data); });',
    'window.addEventListener("click", (event) => event.origin.startsWith("https://trusted.example"));',
    'window.addEventListener("message", handler);',
    'function listen(window) { window.addEventListener("message", (event) => event.origin.startsWith("https://trusted.example")); }',
    'function listen(addEventListener) { addEventListener("message", (event) => event.origin.startsWith("https://trusted.example")); }',
    'channel.addEventListener("message", (event) => event.origin.startsWith("https://trusted.example"));',
    'record.origin.includes("warehouse");',
    'window.addEventListener("message", (event) => { items.map(event => event.origin.includes("warehouse")); });',
    'window.addEventListener("message", (event) => { other.origin.includes("warehouse"); });',
    {
      filename: "generated/listener.ts",
      code: 'window.addEventListener("message", (event) => event.origin.startsWith("https://trusted.example"));',
    },
  ],
  invalid: [
    {
      code: 'window.addEventListener("message", (event) => { if (event.origin.startsWith("https://trusted.example")) accept(event.data); });',
      errors: [{ messageId: "originMatch" }],
    },
    {
      code: 'addEventListener("message", (event) => event.origin.includes("trusted.example"));',
      errors: [{ messageId: "originMatch" }],
    },
    {
      code: 'globalThis.addEventListener("message", function (message) { return message.origin.endsWith("trusted.example"); });',
      errors: [{ messageId: "originMatch" }],
    },
    {
      code: 'self["addEventListener"]("message", (event) => event["origin"]["startsWith"]("https://trusted.example"));',
      errors: [{ messageId: "originMatch" }],
    },
    {
      code: 'const TYPE = "message"; window.addEventListener(TYPE, (event) => event.origin.includes("example"));',
      errors: [{ messageId: "originMatch" }],
    },
  ],
});
