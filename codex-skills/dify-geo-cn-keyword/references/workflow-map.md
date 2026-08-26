# 国内 GEO 生词工作流节点地图

## Business flow

Two upstream inputs run in parallel:

- Enterprise knowledge: `1.开始 → 2-A.调企业知识库 → 3清洗知识库内容`
- Search suggestions: `1.开始 → 2-B.调搜索词接口 → 风险词过滤`

The cleaned enterprise knowledge reaches `4.条件分支`, which selects exactly one generation branch:

- `keyword_type=搜索词` → `5-A搜索词挖掘和生成LLM`
- `keyword_type=问答词` → `5-B问答词挖掘和生成LLM`
- `keyword_type=品牌词` → `5-C品牌词挖掘和生成LLM`

Then:

`selected 5-x output → 6.变量聚合器 → 7、排序代码`

The risk-filter output also enters `7、排序代码`, followed by `8.结束`.

## Node routing

- `1765425297251` — Start inputs: word-pack metadata, company/industry facts, enterprise dataset ID, `keyword_type`, seed keywords, and optional company info.
- `1772455582154` — enterprise knowledge HTTP request.
- `1772455648555` — cleans enterprise knowledge into `result`.
- `17725038564410` — search-term API request.
- `1778558946620` — risk filter intended to return safe `filtered_keywords` and rejected terms.
- `1772522432310` — routes by `keyword_type`.
- `1772455683164` — search-term generator.
- `17725226028060` — Q&A-term generator.
- `17725226062860` — brand-term generator.
- `1772525403789` — aggregates the selected branch's text as one string.
- `1772455024262` — parses LLM/API/filter data, applies qualification and deduplication, sorts sources, and outputs final terms.
- `1765444487278` — exposes only `result` from `final_keywords`.

## Stable external contract

`keyword_type` accepts `搜索词`, `问答词`, or `品牌词`. End exposes:

```text
result: array[string]
```

The sorting node also calculates internal diagnostics:

- `total_count: number`
- `intent_coverage: string`

These are not currently exposed by End. Do not add or rename End fields without explicit integration approval.

## Current count behavior

Each 5-x prompt requests 50 terms. The sorting code returns `final_keywords[:80]`, so generated target, supplemented candidates, and final cap are not the same concept. Diagnose actual expectations before changing count logic.

## Failure signatures

- Empty final result for one type: verify branch match, selected 5-x `text`, aggregator `output`, and sorter `res_llm`.
- All types empty: inspect knowledge cleanup, aggregator/parser inputs, model finish reason, and sorter parsing.
- Unsafe API terms survive: compare search API body, risk-filter JSON, sorter variable wiring, and the parser used for `filtered_keywords`.
- Risk filter removes valid generated terms: verify whether it filters API suggestions only or the selected generated array.
- Fewer than expected terms: compare LLM count, JSON parse success, length/forbidden filters, normalized duplicates, and source ordering.
- Brand terms lack the brand: inspect company-name normalization and the brand-specific qualification path.
- Search terms contain questions or company names: inspect 5-A generation rules before broadening final filters.
- Q&A terms are generic or unnatural: inspect 5-B seed retention, industry fit, and question-form diversity.

## Overseas workflow contrast

The overseas `geo-overseas-query.yml` is a different product with fixed brand/category slots and structured records. Do not use its node map, quotas, or validation errors to diagnose this workflow.
