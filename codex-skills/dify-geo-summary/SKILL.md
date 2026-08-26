---
name: dify-geo-summary
description: Diagnose and resolve business-report problems in the Dify overseas GEO analysis-summary workflow. Use when totals, rates, competitor performance, citation summaries, brand expression, opportunities, recommendations, or final report modules are missing, inconsistent, unsupported, or misleading in geo-overseas-summary.yml.
---

# Dify GEO 分析总结工作流

Turn report-level feedback into a determination of whether the defect is upstream data or summary logic. Use `/Users/jiading/Documents/GitHub/GEO-oversea/workflows/geo-overseas-summary.yml` as the source of truth. Read [workflow-map.md](references/workflow-map.md) when routing among M modules.

## Start every diagnosis

Inspect git status and commit. If clean, fetch and fast-forward only. If sync fails, label the remote unverified and report the local commit. Read `manifest.json` and YAML; YAML overrides cached documentation. Never pull over local changes or restore credentials.

## Diagnose from business evidence

1. Record the displayed conclusion/number, expected result, applicable filters, and underlying record set if available.
2. Identify the responsible report module and trace it through generation, cleanup, parallel convergence, and final merge.
3. Compare incoming answer-analysis arrays with module output before changing summary prompts. Determine whether the workflow received incomplete or wrong data from `geo-overseas-analysis.yml`.
4. Recalculate important counts, rates, rankings, and denominators deterministically where possible; polished prose is not proof.
5. Check grouping keys, duplicate records, empty values, arrays serialized as strings, partial batches, and final overwrite.
6. If evidence is incomplete, state what is proven at report level and which upstream records are needed to confirm origin.

## Deliverable

Lead with `upstream data problem`, `summary logic problem`, or `insufficient evidence`. Then provide the responsible module/node, reproducible calculation or evidence chain, minimal fix, and expected report change.

Do not edit unless asked. Do not make the summary workflow fabricate missing answer-level records. Do not commit or push unless explicitly asked.

## Validate edits

- Parse YAML and check edges/selectors.
- Test complete, partial, empty, and duplicated analysis inputs.
- Verify each parallel branch produces its expected field shape.
- Verify final merge retains every module and does not replace arrays with strings.
- Verify every narrative conclusion is supported by the aggregated records and uses the intended population and denominator.
