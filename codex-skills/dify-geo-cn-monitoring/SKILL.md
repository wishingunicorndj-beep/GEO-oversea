---
name: dify-geo-cn-monitoring
description: Diagnose and safely update the Dify domestic GEO answer-monitoring workflow. Use when brand detection, matched brand, ranking, top recommendation, target or competitor sentiment, neutral-positive rate, competitor coverage, summaries, tags, references, or final monitoring metrics are wrong in geo-cn-monitoring.yml; do not use for query generation, keyword packs, diagnostic-question generation, or the overseas answer-analysis workflow.
---

# Dify 国内 GEO 回答数据监控工作流

Turn monitoring-output feedback into a node-level diagnosis and a testable minimal fix. Use `/Users/jiading/Documents/GitHub/GEO-oversea/workflows/geo-cn-monitoring.yml` as the source of truth. Read [workflow-map.md](references/workflow-map.md) when routing, field ownership, ranking, sentiment, competitor handling, or final output shape matters.

## Business boundary

This workflow analyzes one AI-generated answer and produces domestic GEO monitoring metrics. It does not generate questions, keywords, articles, or reports.

- Input governance normalizes the answer, query, target brand/company aliases, competitor hints, references, and sentence evidence.
- Global entity analysis determines independent entities, ranking structure, modules, summary, and tags.
- The target branch determines valid target mention, matched brand, rank, top-three recommendation, sentiment evidence, and neutral-positive rate.
- The competitor branch completes competitor records, positions, sentiment evidence, and neutral-positive rate.
- Final merge preserves the external monitoring-field contract.

Do not apply `geo-overseas-analysis.yml` translation, answer-level record, or overseas reporting assumptions. Do not apply T1-T4 or domestic keyword-pack count contracts.

## Start every diagnosis

1. Inspect repository status and the current commit in `/Users/jiading/Documents/GitHub/GEO-oversea`.
2. If the working tree is clean, fetch and fast-forward only. Never pull over uncommitted changes.
3. Read `manifest.json` and the current YAML; the YAML overrides this skill and conversation memory.
4. Preserve intentional credential redactions and never invent secrets.

## Diagnose from business evidence

1. Record the input answer, query, target brand/company, competitor list, references, expected metrics, and actual output.
2. Trace the first incorrect value through input governance, global entity extraction, entity validation, the target or competitor branch, final metric merge, and End selectors.
3. Separate model omission or truncation from JSON parsing loss, alias overreach, entity qualification errors, module/ranking errors, evidence attribution errors, sentiment calculation errors, and final-field wiring errors.
4. Verify evidence against the normalized sentence catalog. A name occurrence alone does not prove an independent recommendation, ranking membership, or sentiment ownership.
5. For ranking defects, distinguish ordered choices, independent subjects, comparison-only entities, parallel modules, and non-ranking answers before changing code or prompts.
6. For competitor defects, distinguish user-provided competitor hints from competitors actually evidenced in the answer.
7. If logs are incomplete, request only the adjacent node inputs and outputs needed to confirm the first failing stage.

## Stable contracts

- Preserve the current Start input names and types unless the user explicitly changes the integration contract.
- Preserve End field names and types, including brand detection, matched brand, rank, top recommendation, sentiment, competitor records and positions, summary, tags, references, raw answer, query, and search results.
- `is_top_recommend` means the target brand is within the top three valid ranked choices; it is not a synonym for brand mention.
- Comparison-only or ambiguous sibling-product mentions must not be promoted to independent target detection or ranking.
- Sentiment evidence must remain attributable to the correct entity and sentence; do not transfer adjacent table cells, sibling sections, or comparison-winner evidence.
- Preserve customer-provided brand and competitor names character-for-character at the external boundary.

## Deliverable

Lead with the failed business stage, then identify the responsible node, evidence chain, root cause and confidence, smallest proposed change, affected output fields, and regression cases.

Do not edit unless asked. When asked to fix, change the smallest responsible prompt, code, selector, or configuration. Do not commit or push unless explicitly asked.

## Validate edits

- Parse YAML and verify nodes, edges, selectors, code outputs, model outputs, and End selectors.
- Test ranked lists, unranked single-subject answers, parallel ranking modules, comparison-only mentions, ambiguous aliases, sibling products, tables, missing references, empty competitor lists, malformed/truncated model JSON, and partial evidence.
- Verify target and competitor evidence attribution, rank and top-three consistency, sentiment score/label/reasoning consistency, neutral-positive rate, competitor count/positions, summary/tags, and final field types.
- Confirm no valid field disappears in final merge and no upstream hint becomes unsupported answer evidence.
