---
name: dify-geo-article
description: Diagnose and resolve business-output problems in the Dify overseas GEO article-generation workflow. Use when articles are off-topic, factually weak, competitor-biased, noncompliant, structurally broken, missing, duplicated, incorrectly counted, or inconsistent with knowledge and strategy in geo-overseas-article.yml.
---

# Dify GEO 文章生成工作流

Turn article-quality feedback into a stage-level and node-level diagnosis. Use `/Users/jiading/Documents/GitHub/GEO-oversea/workflows/geo-overseas-article.yml` as the source of truth. Read [workflow-map.md](references/workflow-map.md) when the relevant branch is unclear.

## Start every diagnosis

Inspect git status and commit. If clean, fetch and fast-forward only. If sync fails, label the remote unverified and report the local commit. Read `manifest.json` and YAML; YAML overrides cached documentation. Never pull over local changes or restore credentials.

## Diagnose from business evidence

1. Record the bad passage/output, expected audience and objective, article type, and whether the issue affects one article or the batch.
2. Place it in inputs, knowledge, competitor discovery, topic selection, plan, outline, drafting, compliance, cleanup, aggregation, or N8 output.
3. Trace the defective claim or field backward and find the first stage that introduced it. Confirm suspected nodes are actually connected to N8.
4. Distinguish missing knowledge, wrong retrieval, competitor contamination, poor planning, prompt behavior, parser/data-shape failure, compliance removal, and aggregation loss.
5. Check whether upstream analysis/summary data was already wrong before article generation.
6. For regulated or medical content, identify exact policy/configuration evidence; do not infer Rx/OTC status solely from a product name when authoritative classification is required.
7. If logs are missing, rank hypotheses and request the nearest upstream/downstream outputs around the suspected stage.

## Deliverable

Lead with the failed business stage, then provide responsible node(s), evidence chain, root cause and confidence, smallest fix, affected article branches, and acceptance tests. Explain the overall business flow before code details when the user is unfamiliar with the nodes.

Do not edit unless asked. Preserve article count, compliance, and unrelated branches when making a narrow fix. Do not commit or push unless explicitly asked.

## Validate edits

- Parse YAML and check edges/selectors.
- Verify planned, generated, and merged article counts match.
- Test knowledge-empty, competitor-empty, compliance-hit, and partial-branch cases.
- Confirm the actual aggregation path reaches N8.
- Add content acceptance checks for factual grounding, audience fit, search intent, brand/competitor role, readable structure, and regulatory safety as applicable.
