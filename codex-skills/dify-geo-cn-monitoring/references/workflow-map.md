# 国内 GEO 回答数据监控工作流节点地图

## Business flow

`1.开始 → 2.输入治理、分层别名与双层句子证据（代码） → 3.全局实体、模块排名与摘要LLM → 3v.实体资格、模块排名与摘要校验（代码）`

The validated entity data then enters two parallel branches:

- Target branch: `4a-1.目标独立提及与全量情感证据LLM → 4a-2.目标证据、排名前三与中正率计算（代码）`
- Competitor branch: `4b-1.全量竞品逐证据情感LLM → 4b-2.竞品全量补齐、模块排名与中正率计算（代码）`

Both branches converge at:

`5.最终指标合并（代码） → 结束`

## Stage ownership

| Stage | Owns |
|---|---|
| Start | Raw answer, task/model/query metadata, references/search results, target company/brand, competitor hints, crawler metadata |
| Input governance | Answer cleanup, alias layers, sentence catalog, entity/competitor hints, normalized query |
| Global entity LLM | Ranking structure, entity inventory, modules, anchors, summary, tags |
| Entity validator | Eligible target/competitor inventories, validated ranking membership and positions, safe summary/tags |
| Target LLM | Target mention and positive/negative evidence candidates |
| Target calculator | `brand_detected`, `matched_brand`, `rank_pos`, `is_top_recommend`, target sentiment metrics and evidence |
| Competitor LLM | Per-competitor positive/negative evidence candidates |
| Competitor calculator | Completed competitor records, positions, counts, sentiment metrics and evidence |
| Final merge | External field normalization and preservation of metadata |
| End | Published monitoring fields |

## Output contract

Important outputs include:

- Target: `brand_detected`, `matched_brand`, `rank_pos`, `is_top_recommend`, `is_ranking`.
- Sentiment: `sentiment_score`, `sentiment_label`, `sentiment_reasoning`, `brand_sentiment_analysis`, `sentiment_classic_words`.
- Competitors: `competitor_mentions`, `competitor_pos`, `competitor_count`.
- Content: `summary`, `key_tags`.
- Pass-through metadata: task/model/dataset identifiers, references, company/brand/competitor inputs, raw answer, query, search results.

Inspect the current YAML for exact types and selectors before editing; the End node is the authoritative external contract.

## Failure signatures

- Target name appears but `brand_detected=false`: inspect alias layers, entity qualification, membership, target granularity, then target evidence.
- Target detected but rank/top-three wrong: inspect ranking structure, module boundaries, ordered-choice membership, anchors, and target calculator.
- Ranking detected in an unranked answer: inspect global entity structure classification and validator safeguards.
- Sentiment belongs to the wrong brand: inspect sentence IDs, entity scope, table row/column ownership, comparison direction, and target/competitor calculators.
- Competitors missing or invented: compare answer evidence, user hints, validated competitor inventory, and completion logic.
- Correct branch metrics but wrong final response: inspect final merge inputs/outputs and End selectors.
- Empty or malformed metrics after a long model response: inspect model finish reason and JSON extraction before changing business rules.
