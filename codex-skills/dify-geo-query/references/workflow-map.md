# Query 工作流节点地图

## Business flow

`N1 业务输入 → D0 当前日期 → N2 场景角度生成 → P0 人群画像生成(4-6) → A1 竞品补齐 → A2 竞品拆解`

Then split into two branches:

- Brand: `A3 品牌词生成(10) → A4 品牌词去重本地化 → A5 品牌词格式化校验`
- Category: `B1 品类词生成(40) → B2 品类词去重本地化 → B3 品类词格式化校验`

Merge: `A5 + B3 → M1 数据合并 → M2 多语言实体覆盖修复合并 → End`

## Routing guide

- Persona quality: P0
- Competitor inputs: A1/A2
- Brand query content: A3; localization/dedup: A4; schema/labels: A5
- Category or generic query content: B1; localization/dedup: B2; schema/labels/fallback: B3
- Counts and final array shape: M1/M2
- Truncation: inspect generation/localization model token limits first
- `purchase_intent` wording: inspect A5/B3 mappings and upstream prompts
- Generic phrases such as `specialized product suppliers`: inspect whether B2 was incomplete and B3 fallback ran

## Stable contract

Expected output is 50 records: B01-B10 brand slots plus C01-C40 category slots, unless current YAML states otherwise.
