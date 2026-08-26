# 国内 GEO 品牌诊断测试问题节点地图

## Business flow

Shared preparation:

`开始 → 输出日期 → 竞品清单数据补齐 → 竞品数据拆解`

Four generation branches run in parallel:

- T1: `场景触发生词LLM → 检测格式化 → 数量判断 → 必要时补词LLM → 补词解析 → 合并`
- T2: `品类认知生词LLM → 检测格式化 → 数量判断 → 必要时补词LLM → 补词解析 → 合并`
- T3: `推荐决策生词LLM → 检测格式化 → 数量判断 → 必要时补词LLM → 补词解析 → 合并`
- T4: `品牌直询生词LLM → 检测格式化 → 数量判断 → 必要时补词LLM → 补词解析 → 合并`

The four final arrays converge at `3、数据合并处理 → 结束`.

## Count contract

| Type | Meaning | Minimum |
|---|---|---:|
| T1 | 场景触发 | 60 |
| T2 | 品类认知 | 20 |
| T3 | 推荐决策 | 15 |
| T4 | 品牌直询、品牌对比、竞品直询 | 33 |
| Total | Combined | 128 |

Each formatter exposes `actual_count`, `expected_count`, `is_sufficient`, `deficit`, `existing_queries`, and `formatted_results`. When insufficient, the branch generates exactly the deficit and merges by query text.

## Final output contract

End exposes:

- `result`: `array[string]`; each string contains one JSON object.
- `task_id`, `task_name`, `product_name`, `brand_name`, `core_keyword`, `target_audience`.
- `comps_list`: currently selected from the competitor-completion LLM text; inspect actual shape before downstream use.

Common record fields include `id`, task/brand/core identifiers, `query`, source and question types, scene/persona/priority, decision/cognition/evaluation fields, negative-probe flags, active status, and timestamps. T4 additionally carries `query_type`, `brand_comp`, and `is_competitor`.

## Failure signatures

- One branch below target: compare initial LLM output, formatter count/deficit, supplement output/parser, and per-type merge.
- All branches empty: inspect model outputs, JSON extraction, and shared inputs.
- T4 wrong brands: inspect original competitor input, completion LLM, parsed `comps_list`, then T4 prompt/output.
- Correct per-type counts but wrong total: inspect four variable aggregators and final merge inputs.
- Correct questions but missing metadata: inspect formatter object construction, not the generation prompt.
- Double-escaped output: remember the external array contains JSON strings by design; parse each item once downstream.

## Product boundaries

- `geo-cn-keyword.yml` produces plain domestic keyword-pack strings for one selected type.
- `geo-overseas-query.yml` produces a separate overseas 10-brand-plus-40-category structured dataset.
- This workflow produces domestic T1-T4 diagnostic test questions.
