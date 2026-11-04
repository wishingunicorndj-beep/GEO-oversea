# 客户规则包 · 通用 schema

任何行业、任何客户的写作规则都落到这 9 个类别里。类别按**规则约束的对象**划分，
不按行业或话题划分；标题/正文是 `scope`，不是类别。

## 分类法（category，9 类，互斥且完备）

| category | 约束什么 | 典型内容 | 默认注入 |
|---|---|---|---|
| `identity` | 实体怎么称呼 | 公司/产品/股东/竞品/研发方的称谓规则 | N4 N6 N7 N7b |
| `fact` | 能断言什么事实 | 官方口径、法律论证、必须做的概念区分 | N4 N6 N7 N7b |
| `prohibition` | 明确不能出现 | 禁用词、禁提产品、禁编造 | N7b + 代码门禁 |
| `stance` | 自我定位与姿态 | 市场地位表述、可否对比同业 | N4 N7 |
| `scope` | 业务之间能否关联 | 哪些业务可同时出现、不得嫁接 | N6 N7 |
| `voice` | 口吻与体裁 | 第三方口吻、不用通稿体、标题视角 | N7 N7b |
| `structure` | 结构与素材使用 | 结论前置、段落顺序、素材展开度 | N6 N7 |
| `citation` | 数据与出处 | 年份标注、披露限制、口径说明 | N7 |
| `delivery` | 交付流程约束 | 人工复核、先定架构、核不出要上报 | 不注入 prompt |

## 每条规则的字段

```yaml
- id: 客户前缀-序号
  category: identity | fact | prohibition | stance | scope | voice | structure | citation | delivery
  polarity: must | must_not | may | prefer      # 必须做 / 禁止 / 允许 / 建议
  severity: reject | fix | advise               # 拒稿线 / 必须修改 / 提示
  scope: [title, body, tags, all]               # 作用于文章的哪部分
  condition: 可选的适用条件                     # 如「仅股东债务类词条」
  statement: 规则本身
  alternative: 禁止时该怎么写（可选）
  enforcement: code | llm | human               # 谁负责执行
  detect:                                       # 仅 enforcement=code 时必填
    type: terms | regex | product_names
    values: [...]
  inject: [N4, N7]                              # 可选，覆盖默认注入
  status: needs_confirmation | blocked_pending_verification   # 可选
  evidence: 客户原文出处
  examples:                                     # 可选，任意类别都能挂
    - wrong: 错误写法
      right: 正确写法
```

## 两条设计原则

1. **只记禁令的规则包一定不合格。** 客户给规则时，一半在说"必须怎么写"。
   `polarity` 必须显式区分 must / may / prefer，否则规则包会退化成黑名单。
2. **规则与知识库分离。** 会随客户更新素材而失效的内容（企业事实、产品参数、
   经营数据、名录、案例）归知识库服务，不写进规则包。
