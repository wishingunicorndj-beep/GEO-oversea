# 文章生成工作流节点地图

## Business-level flow

`用户输入 → N1 输入整理 → 企业/产品/营销知识检索 → 知识合并 → N2 文章任务理解 → 竞品处理 → N4/N5 选题 → N6 大纲 → N7 多类文章生成 → 校验与聚合 → N8 最终输出`

## Major responsibility groups

- Inputs and knowledge: N1 plus enterprise, product, and marketing knowledge branches.
- Competitors: search-condition preparation, retrieval, candidate merge, verification, and competitor profile nodes including N3-related nodes.
- Topic planning: N4/N5.
- Outline: N6.
- Drafting: three N7 branches for standard, compliance/medical, and brand-oriented content.
- Safety/compliance: drug configuration, Rx/OTC/off-topic filtering, and branch guards.
- Aggregation: plan counters, article merging, and final N8 output.

## Routing guide

- Hallucinated or missing facts: knowledge retrieval/merge and N4 factual preparation.
- Wrong competitor: trace search condition → candidate discovery → merge → verification; do not edit drafting first.
- Wrong number of articles: compare planning count, branch counts, guards, and merge count.
- Compliance or drug recommendation issue: inspect shared configuration and every compliance consumer.
- Good intermediate rewrite not reflected in final output: confirm that the rewrite/parse node is connected to the final aggregation path.

## Safety note

The repository export may contain `__GIT_REDACTED_TOKEN__`. Treat it as an intentional placeholder and never invent or restore a secret in Git.
