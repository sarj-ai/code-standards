import type { APIRoute, GetStaticPaths } from "astro";

import {
  THIRD_PARTY_PAGE_SIZE,
  thirdPartyCatalog,
  thirdPartyProviderPageHref,
  thirdPartyRulesForProvider,
  thirdPartyRuleAnchor,
  type ThirdPartyProvider,
  type ThirdPartyRule,
} from "../../../lib/third-party-catalog";

interface Props {
  provider: ThirdPartyProvider;
  rules: ThirdPartyRule[];
}

export const getStaticPaths = (() =>
  thirdPartyCatalog.providers.map((provider) => ({
    params: { provider: provider.id },
    props: { provider, rules: thirdPartyRulesForProvider(provider.id) },
  }))) satisfies GetStaticPaths;

export const GET: APIRoute<Props> = ({ props }) => {
  const entries = props.rules.map((rule, index) => {
    const page = Math.floor(index / THIRD_PARTY_PAGE_SIZE) + 1;
    const anchor = thirdPartyRuleAnchor(rule);
    return {
      anchor,
      displayId: rule.displayId,
      family: rule.family,
      href: `${thirdPartyProviderPageHref(props.provider, page)}#${anchor}`,
      summary: rule.summary.replaceAll(/`([^`]+)`/gu, "$1"),
    };
  });
  return new Response(
    JSON.stringify({ entries, provider: props.provider.id }),
    {
      headers: {
        "Cache-Control": "public, max-age=0, must-revalidate",
        "Content-Type": "application/json; charset=utf-8",
      },
    },
  );
};
