---
name: dify-geo-query
description: Diagnose and resolve business-output problems in the Dify overseas GEO query-generation workflow. Use when generated brand/category queries are generic, irrelevant, duplicated, truncated, mislabeled, incorrectly counted, or otherwise fail business expectations, including A/B/M-node issues in geo-overseas-query.yml.
---

# Dify GEO Query 工作流

Turn business feedback about generated queries into a node-level diagnosis and a testable minimal fix. Use `/Users/jiading/Documents/GitHub/GEO-oversea/workflows/geo-overseas-query.yml` as the source of truth. Read [workflow-map.md](references/workflow-map.md) when node routing is needed.

## Start every diagnosis

1. Inspect repository status and the current commit.
2. If the working tree is clean, run `git fetch origin` and `git pull --ff-only`.
3. If synchronization fails, continue locally but state that the remote is unverified and report the local commit.
4. Read `manifest.json` and the current YAML. Current YAML overrides this document and conversation memory.

Never pull over uncommitted changes or restore redacted credentials.

## Diagnose from business evidence

1. Convert the report into: observed result, expected result, affected query type, sample records, and whether the failure is occasional or systematic.
2. Classify the defect as business grounding, persona/competitor context, generation, localization/deduplication, validation/fallback, or final merge.
3. Trace the affected field backward from End and compare adjacent node inputs and outputs. Locate the first node where correct data becomes wrong.
4. Distinguish confirmed cause, strong hypothesis, and unverified possibility. Never infer a node output from the final page alone.
5. If logs are missing, continue with ranked hypotheses and name the smallest exact evidence to collect next; do not request the entire run.
6. Check downstream impact on `geo-overseas-analysis.yml`, because query quality changes the answers later analyzed.

## Deliverable

Lead with the business conclusion, then provide: responsible workflow and node, evidence chain, root cause with confidence, smallest proposed change, affected downstream fields, and regression cases. Explain node names in plain Chinese.

Do not edit unless asked. When asked to fix, modify the smallest responsible prompt/code/configuration and preserve unrelated behavior. Do not commit or push unless explicitly asked.

## Validate edits

- Parse YAML and check nodes, edges, selectors, and output names.
- Preserve 10 brand + 40 category = 50 queries unless the user changes the contract.
- Test normal, incomplete, fallback, duplicate-slot, and intent-quota cases when relevant.
- Include a business-quality check: category queries must name a usable category or procurement object, not merely satisfy JSON/schema checks.
