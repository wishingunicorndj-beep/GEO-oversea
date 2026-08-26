---
name: dify-geo-cn-keyword
description: Diagnose and safely update the Dify domestic GEO keyword-pack generation workflow. Use for Chinese-market 搜索词、问答词、品牌词 quality, count, routing, knowledge, risk-filtering, aggregation, or sorting problems in geo-cn-keyword.yml; do not use for the overseas 10-brand-plus-40-category query workflow.
---

# Dify 国内 GEO 生词生成工作流

Turn domestic keyword-business feedback into a node-level diagnosis and a testable minimal fix. Use `/Users/jiading/Documents/GitHub/GEO-oversea/workflows/geo-cn-keyword.yml` as the source of truth. Read [workflow-map.md](references/workflow-map.md) when branch routing, risk filtering, aggregation, or result counts matter.

## Business-line boundary

This skill is exclusively for the domestic Chinese keyword business line:

- The user selects exactly one `keyword_type`: `搜索词`, `问答词`, or `品牌词`.
- Each type has its own Chinese-language generation prompt and business semantics.
- The End node returns one `result` value containing `array[string]`.

Never apply the overseas `dify-geo-query` contract here. In particular, do not introduce B01-B10/C01-C40 slots, 10 brand + 40 category quotas, personas, purchase-intent labels, multilingual entity evidence, or overseas competitor-domain rules unless the user explicitly redesigns this domestic workflow.

## Start every diagnosis

1. Inspect repository status and current commit in `/Users/jiading/Documents/GitHub/GEO-oversea`.
2. If the working tree is clean, run `git fetch origin` and `git pull --ff-only`.
3. If synchronization fails, continue locally but state that the remote is unverified and report the local commit.
4. Read `manifest.json` and the current YAML. The YAML overrides this document and conversation memory.

Never pull over uncommitted changes. Preserve intentional credential redactions and never invent or restore secrets.

## Diagnose from business evidence

1. Record the selected keyword type, observed output, expected output, seed keywords, industry/company context, sample bad or missing terms, and whether the defect is systematic.
2. Classify the issue as input/branch routing, enterprise knowledge retrieval, knowledge cleanup, search-API input, risk filtering, type-specific generation, variable aggregation, parsing/deduplication, qualification rules, sorting, or final output.
3. Trace `result` backward from End and compare adjacent node inputs and outputs. Locate the first node where correct data becomes wrong or disappears.
4. Distinguish model empty/truncated output, invalid JSON, incorrect branch selection, missing knowledge, unsafe search suggestions, risk-filter bypass, parser fallback, over-filtering, under-filtering, duplication, and final truncation.
5. Do not infer that risk filtering worked merely because the risk node ran. Confirm which field the sorting code actually consumes and whether `filtered_keywords` reaches `final_keywords`.
6. If logs are incomplete, provide ranked hypotheses and request only the nearest upstream/downstream node outputs needed to confirm the cause.

## Domestic output invariants

- Preserve the three selectable keyword types and their separate generation branches.
- Preserve natural Simplified Chinese and real Chinese C-end search or AI-dialog behavior.
- Search terms should be short keyword phrases rather than questions or brand promotions.
- Q&A terms should be natural decision questions rather than noun piles.
- Brand terms should contain the intended brand/company identity and use only supported attributes, qualifications, cases, prices, rankings, or competitors.
- Keep unsafe or illegal search suggestions out of the final result; do not weaken risk filtering to restore count.
- Preserve the End contract `result: array[string]` unless the user explicitly changes the integration.
- Treat the generation target of 50 and the sorter cap of 80 as different current behaviors. Diagnose count loss or inflation from actual node outputs; never replace them with the overseas 50-record schema.

## Deliverable

Lead with the domestic business conclusion, then provide the responsible node, evidence chain, root cause with confidence, smallest proposed change, affected keyword types and final result, and regression cases. Explain node names in plain Chinese.

Do not edit unless asked. When asked to fix, change the smallest responsible prompt, code, selector, or configuration and preserve unrelated keyword types. Do not commit or push unless explicitly asked.

## Validate edits

- Parse YAML and verify nodes, edges, branch case IDs, selectors, variable-aggregator inputs, code outputs, and End output type.
- Test all three keyword types independently; one branch working does not validate the other two.
- Test normal, missing-knowledge, empty-search-API, unsafe-suggestion, malformed-JSON, model-empty/truncated, duplicate, too-short/too-long, and count-boundary cases when relevant.
- Verify the final terms are strings, deduplicated, relevant to the seed and industry, and not lost between the selected LLM branch, aggregator, risk filter, sorter, and End.
- Include business-quality checks appropriate to each type rather than relying only on JSON validity or item count.
