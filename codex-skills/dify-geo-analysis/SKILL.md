---
name: dify-geo-analysis
description: Diagnose and resolve business-output problems in the Dify overseas GEO answer-analysis workflow. Use when brand mentions, rankings, sentiment, competitors, references/media, translations, tables, or final answer-level records are missing, wrong, unstable, or inconsistent in geo-overseas-analysis.yml.
---

# Dify GEO 回答分析工作流

Turn a bad answer-analysis case into a node-level diagnosis and a testable minimal fix. Use `/Users/jiading/Documents/GitHub/GEO-oversea/workflows/geo-overseas-analysis.yml` as the source of truth. Read [workflow-map.md](references/workflow-map.md) when routing among 4a/4b/4c/4d is needed.

## Start every diagnosis

Inspect git status and commit. If clean, fetch and fast-forward only. If sync fails, label the remote unverified and use the named local commit. Then read `manifest.json` and the YAML; YAML overrides cached documentation. Never pull over local changes or restore credentials.

## Diagnose from business evidence

1. Record the displayed defect, expected business meaning, affected answer/run if available, and the smallest supplied evidence (`answer_raw`, screenshot, or a branch output).
2. Route it to target brand (4a), competitor (4b), media/reference (4c), translation (4d), or final merge (5).
3. Compare raw source → LLM semantic candidate → code normalization/filter → final merge. Locate the first divergent layer.
4. Check both false negatives and false positives. A value present in raw text is not automatically a valid competitor, citation, or sentiment signal.
5. Separate extraction failure, semantic misclassification, parser rejection, fallback invention, and downstream overwrite.
6. If historical logs are unavailable, rank likely causes and request only the two adjacent outputs that can distinguish them.
7. Check whether the issue is inherited from `geo-overseas-query.yml` or propagated into `geo-overseas-summary.yml`.

## Deliverable

Lead with whether this workflow caused the business issue. Then provide: responsible branch/node, evidence chain, root cause and confidence, minimal fix, fields affected, and regression cases. Explain technical structures in plain Chinese.

Do not edit unless asked. When asked to fix, avoid large prompt rewrites unless evidence shows the current contract is fundamentally wrong. Do not commit or push unless explicitly asked.

## Validate edits

- Parse YAML and check edges/selectors.
- Test a good case, a known bad case, empty `search_results`, citations only in `answer_raw`, and malformed LLM JSON.
- Ensure fallbacks do not invent brands, media, URLs, titles, rankings, or sentiment.
- Verify node `5` preserves corrected upstream values.
- For competitor tests, include citation-label noise, attributes/specifications, target aliases, configured and discovered competitors, and unrelated real brands.
- For media tests, compare all URLs visible in `answer_raw` with 4c output and distinguish invalid/non-link labels from valid URLs.
