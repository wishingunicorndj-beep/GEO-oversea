# 回答分析工作流节点地图

## Shared entry

`1 开始 → 2 输入治理 → 3 is_ranking LLM → 3v`

## Parallel branches

- Target brand: `4a-1 → 4a-2 → 4a-3 → 4a-4 → 5`
- Competitors: `4b-1 → 4b-2 → 4b-3 → 5`
- Media/references: `4c-1 → 4c-2 → 5`
- Translation: `3 → 4D-0 翻译前清理引用 → 4d → 4d-2 → 4d-3 → 5`
- Final: `5 → End`

## Routing guide

- Target recognition/rank/sentiment: inspect the whole 4a chain; later nodes may overwrite earlier sentiment.
- False competitors: 4b-1 semantic extraction, 4b-2 normalization/filtering, 4b-3 final shaping.
- Sources, `brand_media`, `competitor_media`: 4c-1 candidates and 4c-2 URL normalization/filtering.
- Missing references: compare `answer_raw`, `references`, `search_results`, 4c-1 output, then 4c-2 output.
- Chinese links or broken Markdown tables: 4D-0 and the 4d chain.
- Correct upstream but wrong final output: inspect node 5 for overwrite/default behavior.

## Important distinction

An entity visible in an answer is not automatically a competitor. Citation labels, favicon labels, institutions, platforms, specifications, table criteria, and product attributes require semantic exclusion or downstream filtering.
