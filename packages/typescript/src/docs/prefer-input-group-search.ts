/** @fileoverview prefer-input-group-search — the documentation and executable examples of `@sarj/prefer-input-group-search`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_INPUT_GROUP_SEARCH_DOCUMENTATION = {
  summary: "Require search icons and shared Input controls in the same visual wrapper to use InputGroup.",
  rationale: "The shared compound control provides consistent spacing, focus behavior, and accessible composition.",
  remediation: "Compose the search icon and field with InputGroup, InputGroupAddon, and InputGroupInput.",
  category: "style",
  limitations: [
    "Opposite branches of the same conditional expression and icons with explicit interaction handlers are excluded; arbitrary component behavior is not inferred.",
    "Only Search and Input bindings imported from the recognized shared modules are paired.",
    "The file must import InputGroup, proving that the repository has adopted that optional primitive.",
  ],
  examples: [
    { id: "grouped-search", title: "Use the shared input group", outcome: "no-match", files: [{ path: "src/search.tsx", source: "import { Search } from 'lucide-react'; import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'; const field = <InputGroup><InputGroupAddon><Search /></InputGroupAddon><InputGroupInput /></InputGroup>;" }], focusPath: "src/search.tsx", expectedCount: 0, public: true },
    { id: "loose-search-input", title: "Do not pair loose search controls", outcome: "match", files: [{ path: "src/search.tsx", source: "import { Search } from 'lucide-react'; import { Input } from '@/components/ui/input'; import { InputGroup } from '@/components/ui/input-group'; const field = <div><Search /><Input /></div>;" }], focusPath: "src/search.tsx", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
