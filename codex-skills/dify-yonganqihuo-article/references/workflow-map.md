# 永安期货文章工作流节点地图

## Business flow

`用户输入 → N1 代码预处理 → 企业/产品知识库检索 → 知识库合并 → N4 GEO画像 → N5 迭代计划 → N6 大纲拆分 → 迭代生文 → N8 发布前复检 → N8 结果合并 → 输出`

Inside each article iteration:

`迭代开始 → N7 生文 → N7-3 客户规则终审 → N7-4 强制合规兜底`

## Node routing

- `gt_n1_code` — normalizes article count, style/type, region, content/compliance mode, competitor need, and knowledge queries.
- `gt_http_ent_kb` / `gt_http_prod_kb` — retrieve enterprise and product knowledge.
- `gt_code_kb_merge` — produces `merged_kb`; inspect here before blaming downstream prompts for missing facts.
- `gt_llm_geo` — creates the Yong'an Futures GEO profile and content grounding.
- `gt_llm_plan` — plans the requested article batch.
- `gt_code_split` — converts plans into `merged_plans`; article-count and outline-shape failures often become visible here.
- `gt_iteration` — executes one drafting chain per plan and returns `structured_output` objects.
- `gt_llm_gen` — first article draft.
- `gt_llm_polish` — applies Yong'an Futures client-specific rules.
- `gt_code_data` — deterministic compliance and structure fallback for each draft.
- `gt_code_clean` — publication review over the iteration array; outputs `cleaned_articles`.
- `gt_code_merge` — final aggregation.
- `gt_end` — exposes the external output contract.

## Stable external contract

Start includes `keyword_pack`, company/industry facts, enterprise and product dataset IDs, task information, media/style/type, `article_count`, and optional known competitors.

End exposes five arrays:

- `article_titles`
- `final_article_text`
- `generated_articles_list`
- `article_tags`
- `quality_scores`

Do not rename or change these output types without explicit integration approval.

## Failure signatures

- Empty or truncated N7 output: inspect model `text`, `finish_reason`, token usage, and N7-3 input before changing parsers.
- Correct N7 but wrong final article: compare N7-3, N7-4, and N8 publication review to find the first rewrite.
- Wrong article count: compare requested count, N1 normalized count, N5 plan count, N6 `merged_plans`, iteration result count, `cleaned_articles`, and all five final arrays.
- Unsupported claim: trace draft sentence to `merged_kb` and user inputs; remove or qualify it rather than manufacturing evidence.
- Missing whole article after a compliance hit: inspect whether N7-4 returns a valid object and whether N8 cleanup drops malformed objects.

## Safety

The DSL may contain redacted connection values. Keep redactions intact and never restore secrets from memory or guesses.
