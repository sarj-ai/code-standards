# `SARJ202` / `no-comment-cruft` (IaC) — evidence

Behaviour is specified by
[the tests](../../packages/iac/tests/rules/test_no_comment_cruft.py). This file
holds what a test cannot carry: the measurements behind each threshold.

The rule flags two shapes in `.tf` / `.hcl` / config files — commented-out HCL
and section-banner comments. The curation history of the commented-out half
(the run-dominance guard, and the two false-positive classes it fixed) is in the
module docstring, which is where `sarj-iac-lint explain` reads from.

## One banner, one finding (2026-07-31 sweep)

The canonical Terraform banner is three lines:

```hcl
################################################################################
# Cluster
################################################################################
```

Only the two rule lines are banner-shaped — the title between them is not — so
the rule reported **the same defect twice**, once at the top and once at the
bottom.

Measured over **1,424 content-unique `.tf` files** (terraform-aws-vpc,
terraform-aws-eks, terraform-aws-components and a first-party IaC tree):

| | before | after |
| --- | --- | --- |
| banner findings | 748 | 383 |
| commented-out findings | 177 | 177 |
| registry total | 946 | 581 |

Roughly 83% of banners were double-counted. The second report carries no
information the first did not, and volume is what gets a rule switched off.

`_banner_group_leaders` reports the FIRST rule line of each banner group. A
group is the maximal set of banner lines separated only by comment lines — the
same "run" notion the commented-out half already uses — so the title keeps the
two rules one banner, while real HCL or a blank line starts a new one.

Detection is unchanged and that is pinned three ways: two banners in a file are
still two findings, a lone divider with no title is still one finding, and two
rule lines separated by a blank line are still two banners. A mutant that
reports the first banner of the FILE rather than of each group fails two of
those.

The banner **policy** is deliberately untouched. Twenty-one findings read at
source over the OSS Terraform corpus were 14/14 accurate on the shapes sampled;
the volume reflects that `terraform-aws-modules` uses ASCII banners pervasively,
which is a house-style disagreement rather than a detection question.
