# 定制生文工作流生成工具

从客户资料生成 GEO 定制生文工作流：**客户资料 → 规则包 → 定制工作流 yml → 验收报告**。

母版是仓库根目录的 `workflows/通用生文工作流.yml`（18 节点）。本项目只做定制生成，**不改母版**。

## 快速开始

```bash
# 1. 启动服务
python3 server.py                      # http://127.0.0.1:8901

# 2. 打开界面
open http://127.0.0.1:8901/upload.html
```

模型配置读取 `~/Documents/GitHub/kb-cleaning-workbench/nano.local.json`
（可用环境变量 `AI_PARSE_BASE_URL` / `AI_PARSE_AUTHORIZATION` / `AI_PARSE_MODEL` 覆盖）。

## 命令行用法

```bash
# 一条命令跑完：资料 → 抽取 → 规则包 → 工作流
python3 scripts/build_client.py /path/to/客户资料 \
    --slug qianhai_life --name "前海人寿保险股份有限公司" --short 前海人寿

# 断点续跑（改完规则包后只重新生成 yml）
python3 scripts/build_client.py ... --from-rules
```

## 目录

```
server.py            HTTP 服务
scripts/
  extract_client_docs.py   docx/xlsx → 纯文本（带来源标记）
  extract_rules.py         ★模型抽取写作规则（唯一调模型的阶段）
  draft_to_rules.py        初稿 → 规则包（含 detect 推导、schema 校验）
  build_client_workflow.py 规则包 → 定制 yml（注入 prompt + 代码门禁）
  build_client_evaluator.py 规则包 → 质量评估器（代码可判 + 模型判定）
  run_judgement.py         ★批量执行模型判定
  build_client.py          四步串联
report/
  upload.html      导入客户资料（填写信息 / 上传 / 抽取）
  rules/index.html 规则包评审（逐条勾选、裁决冲突、生成工作流）
  index.html       验收报告（对照规则核验文章）
clients/<slug>/    各客户数据
  _client.json     客户信息
  rules.yaml       规则包（入库）
  _draft.json      抽取初稿（入库，便于复查）
  _docs/ _raw/     原始资料与转出文本（不入库）
output/            生成的 yml（不入库，可由规则包重新生成）
```

## 规则包设计

规则分 9 类，按**约束对象**划分，与行业无关：

| category | 约束什么 | 是否注入 prompt |
|---|---|---|
| `identity` | 实体怎么称呼 | ✓ |
| `fact` | 能断言什么事实 | ✓ |
| `prohibition` | 明确不能出现 | ✓ |
| `stance` | 自我定位 | ✓ |
| `scope` | 业务之间能否关联 | ✓ |
| `voice` | 口吻与体裁 | ✓ |
| `structure` | 文章结构 | ✓ |
| `citation` | 数据与出处 | ✓ |
| `delivery` | 交付流程 | **✗ 不注入、不判定** |

每条规则的关键字段：

- `polarity`：must / must_not / may / prefer —— **只有 must_not 才推导禁用词表**，否则会把"正确写法"当成"禁用词"，导致反向误判
- `enforcement`：code（词表/正则可确定性检出）/ llm（需语义判断）/ human（流程项）
- `scope_note`：判定边界，写清"管什么、不管什么" —— **没有边界的规则会导致模型判定漂移**
- `evidence`：客户原文出处

### 规则与知识库的边界

规则包只描述「该怎么写」，不承载「这家公司是什么样」。
企业事实、产品参数、经营数据、荣誉、机构名录、案例素材由知识库服务提供。
判断标准：**会随客户更新素材而失效的，归知识库；描述表达禁区的，归规则包。**

## 已知限制

- **抽取有随机性**：同一批资料两次抽取结果不完全一致（约 20% 差异），关键风险项稳定覆盖，细节规则可能变动。规则包标为 `0.1.0-draft`，需人工复核后转正。
- **生成基于母版**：拓扑冻结 18 节点，不改连线。需要新增节点的客户走不了这条路。
- **抽取阶段同步阻塞**：`/api/extract` 要等 3-5 分钟，期间刷新页面会看不到进度（任务本身仍在后台完成）。
