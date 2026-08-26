---
name: dify-geo-cn-diagnostic-questions
description: Diagnose and safely update the Dify domestic GEO brand-diagnostic test-question workflow. Use when T1 scene, T2 category-cognition, T3 recommendation-decision, T4 brand/competitor questions, competitor completion, counts, supplementation, structured records, or final merging are wrong in geo-cn-diagnostic-questions.yml; do not use for domestic keyword packs or overseas 10+40 queries.
---

# Dify 国内 GEO 品牌诊断测试问题工作流

Turn diagnostic-question feedback into a node-level diagnosis and a testable minimal fix. Use `/Users/jiading/Documents/GitHub/GEO-oversea/workflows/geo-cn-diagnostic-questions.yml` as the source of truth. Read [workflow-map.md](references/workflow-map.md) when T1-T4 routing, count supplementation, competitor handling, or output shape matters.

## Business-line boundary

This workflow generates structured questions that are later sent to AI systems to diagnose brand visibility. It is not the final report and not a general keyword-pack generator.

- T1: scene-trigger questions.
- T2: category-cognition questions.
- T3: recommendation/decision questions.
- T4: client-brand, competitor-comparison, and competitor-direct questions.

Do not apply the domestic `geo-cn-keyword.yml` three-way search/Q&A/brand keyword contract. Do not apply the overseas `geo-overseas-query.yml` B01-B10/C01-C40, 10+40, multilingual, or competitor-domain contract.

## Start every diagnosis

1. Inspect repository status and current commit in `/Users/jiading/Documents/GitHub/GEO-oversea`.
2. If the working tree is clean, fetch and fast-forward only. Never pull over uncommitted changes.
3. Read `manifest.json` and the current YAML; the YAML overrides this skill and conversation memory.
4. Preserve intentional credential redactions and never invent secrets.

## Diagnose from business evidence

1. Record the affected T type, bad record or missing count, task/brand/product/core keyword, target audience, competitor input, and expected result.
2. Trace the record from initial LLM generation through formatting, quantity decision, optional supplement generation/parsing, per-type merge, and final T1-T4 merge.
3. For T4 defects, trace competitor completion and competitor parsing before changing generation prompts.
4. Distinguish model empty/truncated output, malformed JSON, parser loss, insufficient initial count, supplement failure, duplicate removal, wrong field normalization, competitor contamination, and final merge loss.
5. Confirm the first node where correct data becomes wrong. Do not infer intermediate outputs from the final `result` alone.
6. If logs are incomplete, provide ranked hypotheses and request only the adjacent node inputs/outputs needed to confirm the cause.

## Stable contracts

- Preserve target minimums unless the user changes the product contract: T1=60, T2=20, T3=15, T4=33; expected total=128.
- Preserve the End metadata fields and `result: array[string]`.
- Each item in `result` is a JSON-serialized structured record, not a plain keyword string.
- Preserve T-specific semantics and fields: scenes/personas for T1, cognition dimensions for T2, decision levels for T3, and query/competitor/evaluation fields for T4.
- Preserve customer-provided competitor names character-for-character; competitor completion should produce the configured three-brand set without cross-industry contamination.
- Do not restore counts by adding irrelevant, duplicated, unsafe, or off-topic questions.

## Deliverable

Lead with the failed business stage, then provide the responsible T branch and node, evidence chain, root cause with confidence, smallest proposed change, affected final fields/counts, and regression cases.

Do not edit unless asked. When asked to fix, change the smallest responsible prompt, code, selector, or configuration and preserve unrelated T branches. Do not commit or push unless explicitly asked.

## Validate edits

- Parse YAML and verify nodes, edges, branch selectors, aggregators, code outputs, and End selectors.
- Test T1-T4 independently, then test the combined result.
- Test sufficient, insufficient/supplement, malformed/truncated JSON, duplicate, missing competitor, one/two/three competitor, and partial-branch cases when relevant.
- Verify target counts, structured-field types, unique query text, core-keyword anchoring, and final total.
- Verify every `result` string can be parsed into one JSON object and no valid record disappears during merging.
