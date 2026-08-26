---
name: dify-yonganqihuo-article
description: Diagnose and safely update the Dify Yong'an Futures brand-customized article-generation workflow. Use when 永安期货 articles are missing, truncated, off-topic, weakly grounded, noncompliant, incorrectly branded, malformed, or incorrectly counted in yonganqihuo0825.yml.
---

# Dify 永安期货定制文章工作流

Turn business feedback about 永安期货 article generation into a stage-level diagnosis and a testable minimal fix. Use `/Users/jiading/Documents/GitHub/GEO-oversea/workflows/yonganqihuo0825.yml` as the source of truth. Read [workflow-map.md](references/workflow-map.md) when node routing, iteration, or output shape matters.

## Start every diagnosis

1. Inspect repository status and the current commit in `/Users/jiading/Documents/GitHub/GEO-oversea`.
2. If the working tree is clean, run `git fetch origin` and `git pull --ff-only`.
3. If synchronization fails, continue locally but state that the remote is unverified and report the local commit.
4. Read `manifest.json` and the current YAML. The YAML overrides this document and conversation memory.

Never pull over uncommitted changes. Preserve intentional redactions such as `__GIT_REDACTED_TOKEN__`; never invent or restore credentials.

## Diagnose from business evidence

1. Record the bad article passage or output, expected audience/search intent, requested article count, and whether the failure affects one iteration or the whole batch.
2. Place the defect in input preprocessing, knowledge retrieval/merge, GEO profiling, planning, outline splitting, drafting, client-rule review, deterministic compliance fallback, publication review, or final merge.
3. Trace the affected field backward from End and locate the first node where correct data becomes wrong. Confirm the node is on the live path to `gt_end`.
4. Distinguish missing knowledge, incorrect knowledge attribution, prompt behavior, model truncation/empty output, parser or data-shape failure, compliance rewriting, iteration loss, and final aggregation loss.
5. When facts are wrong or unsupported, compare the enterprise/product knowledge inputs and `merged_kb` before changing generation prompts. Do not make the workflow fabricate missing facts.
6. When logs are incomplete, provide ranked hypotheses and request only the nearest upstream and downstream node outputs needed to confirm the origin.

## Yong'an Futures invariants

- Keep the workflow brand-specific to 永安期货. Do not silently generalize it into the overseas article workflow.
- Preserve the existing start variables and End outputs unless the user explicitly changes the integration contract.
- Preserve the chain `N7 generation → N7-3 client review → N7-4 deterministic compliance → N8 publication review → N8 merge`.
- Treat financial claims, rankings, returns, risk statements, regulatory qualifications, product capabilities, fees, service scope, and competitor comparisons as evidence-sensitive. Keep only claims supported by the provided inputs or retrieved knowledge.
- Do not confuse 永安期货 with another entity or attribute an external entity's facts, products, licenses, or achievements to it.
- Keep risk disclosures and deterministic compliance checks intact when editing prose prompts.
- Preserve the requested article count through plan, split, iteration, cleanup, and merge.

## Deliverable

Lead with the failed business stage, then provide the responsible node, evidence chain, root cause with confidence, smallest proposed change, affected downstream fields, and acceptance tests. Explain node names in plain Chinese.

## Edit authorization

- Default to proposal-only mode: explain exactly which nodes, prompt clauses, or code blocks should change and provide copy-ready replacement text, but do not edit the workflow file.
- Requests such as “怎么改”, “帮我改一下”, or “调整一下提示词” do not by themselves authorize a file edit. Treat them as requests for a proposed revision.
- Edit `yonganqihuo0825.yml` only after the user explicitly authorizes file mutation with wording such as “现在修改文件”, “直接落盘”, or an equally clear instruction.
- When file editing is explicitly authorized, modify the smallest responsible prompt, code, or configuration and preserve unrelated brand/compliance behavior.
- Do not commit or push unless explicitly asked.

## Validate edits

- Parse YAML and verify nodes, edges, selectors, iteration inputs/outputs, and End output names.
- Test normal, knowledge-empty, partial-knowledge, model-empty/truncated, compliance-hit, malformed-JSON, partial-iteration, and multi-article cases when relevant.
- Verify planned, iterated, cleaned, and merged article counts agree.
- Confirm every final article retains valid title, body, tags, and quality data in the existing output arrays.
- Perform business-quality checks for factual grounding, 永安期货 brand attribution, search-intent fit, readable structure, financial compliance, complete closing, and absence of unsupported promises or rankings.
