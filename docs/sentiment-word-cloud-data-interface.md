# 情感词云数据接口

## 1. 适用范围

本接口用于单条 `answer_raw` 的目标品牌情感词云输出。接口只返回目标品牌相关内容，不拆分竞品词云。

## 2. 输出字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `sentiment_word_clouds` | object | 是 | 正面、中性、负面词云明细 |
| `sentiment_word_clouds.positive` | array[object] | 是 | 正面词云，全部返回，不限制 Top N |
| `sentiment_word_clouds.neutral` | array[object] | 是 | 中性词云，全部返回，不限制 Top N |
| `sentiment_word_clouds.negative` | array[object] | 是 | 负面词云，全部返回，不限制 Top N |
| `term` | string | 是 | `answer_raw` 中实际出现的原文连续片段 |
| `count` | integer | 是 | 该词在有效目标品牌情感范围内的实际出现次数 |
| `sentiment_word_cloud_summary` | object | 是 | 三类词云的次数汇总 |
| `positive_count` | integer | 是 | 正面词云明细 `count` 之和 |
| `neutral_count` | integer | 是 | 中性词云明细 `count` 之和 |
| `negative_count` | integer | 是 | 负面词云明细 `count` 之和 |
| `total_count` | integer | 是 | 三类次数之和 |

## 3. 响应示例

```json
{
  "sentiment_word_clouds": {
    "positive": [
      {
        "term": "性价比高",
        "count": 3
      },
      {
        "term": "口碑好",
        "count": 2
      }
    ],
    "neutral": [
      {
        "term": "使用方法",
        "count": 2
      }
    ],
    "negative": [
      {
        "term": "价格偏高",
        "count": 2
      }
    ]
  },
  "sentiment_word_cloud_summary": {
    "positive_count": 5,
    "neutral_count": 2,
    "negative_count": 2,
    "total_count": 9
  }
}
```

## 4. 统计和校验规则

1. `term` 必须是 `answer_raw` 中连续存在的原文片段，不允许 AI 改写、总结、扩展或替换同义词。
2. 正面、中性和负面 `term` 去除首尾空白后，字符长度均不得超过 10 个字符；超过 10 个字符的候选词直接丢弃。
4. 只统计目标品牌相关的评价或事实描述；竞品相关内容不进入词云。
5. 同一词在同一条回答中出现多次，按实际有效出现次数累计。例如出现 3 次，`count` 为 `3`。
6. 同义词不合并。例如“价格偏高”和“价格较贵”分别作为两个词统计。
7. 同一个原文词在不同情感下，按“词语 + 情感”分别统计，不跨情感合并。
8. 词频由代码统计，不能使用模型返回的次数。
9. 每类结果默认返回全部词条，前端根据展示场景自行截取 Top N。
10. 每类结果按 `count` 降序排列；次数相同时，按词语在有效目标品牌内容中的首次出现顺序排列。
11. 没有结果时返回空数组和 `0` 汇总值，不返回 `null`。

## 5. 内部处理建议

接口不需要暴露原文定位信息，但工作流内部应保留句子或片段归属，用于避免把竞品评价统计到目标品牌。

建议内部流程如下：

1. 模型从目标品牌相关情感证据中提取原文候选词。
2. 代码校验候选词是否原样存在于对应 `answer_raw` 片段。
3. 代码校验目标品牌归属、情感分类和正负词长度限制。
4. 代码按“情感 + 原文词”统计有效出现次数。
5. 代码生成三个数组和汇总字段。

## 6. 与现有字段的关系

新增以下字段：

- `sentiment_word_clouds`
- `sentiment_word_cloud_summary`

现有 `sentiment_classic_words` 字段继续保留，用于兼容旧接口；新词云逻辑不复用该字段。
