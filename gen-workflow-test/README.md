# 定制生文工作流生成与验收平台

把「客户资料」变成「可运行的定制定制生文工作流」，并对其产出做规则合规验收。一套闭环，面向多个客户复用。

**一句话**：客户资料进 → 规则包出 → 基于母版生成客户版工作流 → 生文后上传 JSON → 按规则测评 → 出报告。

---

## 一、这是什么

给 GEO 生文业务用的工具。原来每接一个客户，都要人工读一遍客户资料、手工改工作流 yml；改了母版还要逐个客户同步。

这个平台把这件事变成流水线：

| 环节 | 输入 | 输出 | 谁来做 |
|---|---|---|---|
| ① 抽取规则 | 客户资料（docx/xlsx） | 规则包 `rules.yaml` | 模型自动 + 人工评审 |
| ② 生成工作流 | 规则包 + 母版 yml | 客户版生文工作流 yml | 脚本，秒级 |
| ③ 生文 | 客户版工作流 | 文章 JSON | **Dify 平台**（本平台不参与） |
| ④ 验收 | 文章 JSON + 规则包 | 验收报告 + 看板 | 代码 + 模型 |

**拓扑冻结**：所有客户版工作流都是同一个 18 节点母版，只换规则包内容，不增删节点、不改连线。这样母版修 bug 能一键回灌所有客户。

**规则与知识库分离**：规则包只描述「该怎么写」（禁用词、口吻、结构要求），不承载「这家公司是什么样」（企业事实、产品参数、经营数据）。后者由知识库服务提供。

---

## 二、快速开始

### 网页操作

```
1. 导入客户资料   /upload.html       填客户信息 + 拖入资料 → 自动抽取
2. 规则包评审     /rules/            裁决冲突、增删改规则、确认转正 → 生成工作流
3. 验收报告       /index.html        选客户 → 新建批次 → 上传文章 JSON → 出报告
```

**工作流的正确使用顺序就是上面 1→2→3**，侧栏也是按这个顺序排的。

### 规则包评审页能做什么

| 操作 | 说明 |
|---|---|
| 裁决冲突 | 二选一 / 写自定义口径 / 删除该项（软删，记录保留）；可勾选「应用到规则」把结论写入指定规则的指定字段 |
| 新增规则 | 结构化表单，自动分配未占用的 id；人工录入固定为「模型判定」类，出处记「人工录入」 |
| 编辑规则 | 就地展开表单，id 不变（历史批次引用不断） |
| 移除规则 | 取消勾选或点「移除」→ 软删除：记录保留在 yaml 里，不再注入工作流也不参与验收，可随时恢复 |
| 确认转正 | 前置条件：冲突全部裁决 + 规则校验通过；去掉版本号里的 `-draft` |

**裁决不会自动改规则**：必须显式选择目标规则和字段。改 `statement` / `condition` 影响生文与验收；改 `scope_note` 只影响验收判定。被覆盖的原文记在规则的 `field_history` 里。

### 命令行

```bash
# 一条命令跑完：资料 → 抽取 → 规则包 → 工作流
python3 scripts/build_client.py /path/to/客户资料 \
    --slug qianhai_life --name "前海人寿保险股份有限公司" --short 前海人寿

# 断点续跑（改完规则包只重新生成 yml）
python3 scripts/build_client.py ... --from-rules
```

### 本地启动

```bash
python3 server.py                    # http://127.0.0.1:8901
```

依赖只有 `PyYAML` 和 `PyMySQL`（无数据库时可不装）。模型配置见第五节。

---

## 三、数据格式

### 3.1 客户资料（上传）

支持 `.docx` `.xlsx` `.txt` `.md` `.csv` `.pdf`。建议包含：

- 客户写作规范 / 评审纪要
- 语料问题反馈（客户指出错误写法的地方，信息量最大）
- 企业信息提报表

**上传时填三个字段**：客户标识（`slug`，小写字母数字下划线）、客户简称（用于工作流文件名）、客户全称。

> 资料目录里混入的非客户文件（样板稿、测试 json 等）可在抽取时按文件序号排除。

### 3.2 规则包 `rules.yaml`

```yaml
meta:
  client_id: qianhai_life
  client_name: 前海人寿保险股份有限公司
  client_short: 前海人寿
  industry: 人身保险
  version: 0.1.0-draft        # draft 表示未人工评审，转正去掉后缀
  topology: generic-18        # 拓扑冻结标识
  extraction:                 # 抽取来源（可追溯）
    model: openai/gpt-6.1-sol
    source_files: [...]
  note: 由脚本从客户资料自动抽取，需人工复核后转正

rules:
  - id: QIANHA-01
    category: identity        # 见下表，9 类
    polarity: must_not        # must | must_not | may | prefer
    severity: fix             # reject 拒稿线 | fix 必须改 | advise 建议
    scope: [title, body]      # 作用于文章哪部分
    condition: 股东债务危机类稿件   # 可选，适用条件
    statement: 标题不得直接使用"宝能集团"，应以"股东"代指
    scope_note: |             # 判定边界 —— 最重要的字段
      限制标题中的股东负面实体称谓，不等于禁止正文出现该实体。
    alternative: 使用「股东债务危机…」等弱化实体的标题
    detect:                   # 仅 enforcement=code 时存在
      type: terms             # terms | regex | product_names | replace | brand_combo | required
      values: [宝能集团]
    enforcement: code         # code 确定性检出 | llm 需语义判断 | human 流程项
    evidence: 标题必须隐去"宝能集团"，改用"股东"代指
    source_file: 文件5：评审会纪要
    examples:
      - wrong: 宝能集团债务危机，会影响前海人寿的保单吗？
        right: 股东债务危机，会影响前海人寿的保单吗？

injection_map:                # 哪类规则注入哪个节点
  N4: [identity, fact, stance]
  N6: [identity, scope, structure, voice]
  N7: [fact, citation, scope, structure, voice]
  N7b: [prohibition, identity, fact, citation, structure, voice]
  code_gate: [prohibition, identity]

conflicts:                    # 客户资料之间互相矛盾
  - topic: 标题实体限制的强度
    detail: 同一纪要一处写"必须隐去"，另一处写"尽量不提"
    party_a: 标题必须隐去"宝能集团"
    party_b: 标题尽量不提，正文可适度提及
    from_a: 文件5 A1
    from_b: 文件5 冲突清单

not_rules:                    # 被刻意排除的内容（解释为什么不算规则）
  - content: 成立时间、注册资本、客户数量
    why: 属于会随素材更新的企业事实，不是写作规范

stats:
  total: 60
  by_category: {...}
  by_polarity: {...}
  by_enforcement: {...}
  delivery_excluded: 10       # 流程项，不注入、不判定
```

**9 个 category，按约束对象划分，与行业无关**：

| category | 约束什么 | 注入 prompt |
|---|---|---|
| `identity` | 实体怎么称呼（公司/产品/股东/竞品） | ✓ |
| `fact` | 能断言什么事实、必须做的区分 | ✓ |
| `prohibition` | 明确不能出现的词/产品/编造内容 | ✓ |
| `stance` | 自我定位、可否与同业比较 | ✓ |
| `scope` | 业务之间能否关联 | ✓ |
| `voice` | 口吻体裁（第三方口吻、不用通稿体） | ✓ |
| `structure` | 文章结构、素材展开度 | ✓ |
| `citation` | 数据与出处（年份标注、披露限制） | ✓ |
| `delivery` | 交付流程（人工复核、先定架构） | **✗ 不注入、不判定** |

**两条硬规则**（踩过坑，写在这里防复发）：

1. **只有 `must_not` 才推导禁用词表**。`must`/`may` 类规则引号里的是「正确写法」，放进禁用词表会反向误判。
   例：`must「应采用『中小型险企』」` —— 『中小型险企』是正确写法，不是禁用词。

2. **`scope_note` 是必需字段**。没有判定边界的规则会让模型判定漂移。
   实测：不写边界时，同一批 10 篇文章判出 24 处违规，其中 20 处是误判；补了边界后降到 4 处，全部成立。

**另外几类取值不报错但会让规则静默失效**，`rule_schema.py` 会在保存时拦截：

| 写错的内容 | 后果 |
|---|---|
| `category` 拼错（如 `prohibit`） | 不在 `injection_map` 里，工作流 prompt 中完全没有这条 |
| `scope` 写成 `all` / 只写 `tags` | 评估器 targets 为空，永远判 pass（漏判） |
| `enforcement=code` 但没有 `detect` | 永远判 unclear |
| `detect.type` 是 `replace`/`required` 等 | 门禁支持但验收评估器不支持，永远判 unclear |

人工录入只允许 `enforcement=llm`，从入口避免后两类问题。

**软删除**：取消勾选或点「移除」的规则保留在 yaml 里（`status: dismissed`），但不注入工作流、不参与判定，可在「已移除的规则」里恢复。id 不复用 —— 已删除的编号不会再分配给新规则，否则历史批次的 `rules_snapshot.yaml` 会指向另一条规则。

### 3.3 生文输出 JSON（从 Dify 导出）

工作流 end 节点返回的结构，直接上传即可：

```json
{
  "article_titles": ["标题1", "标题2"],
  "quality_scores": ["自评1", "自评2"],
  "final_article_text": "所有文章拼接",
  "generated_articles_list": ["<h2>正文1</h2>...", "<h2>正文2</h2>..."],
  "article_tags": ["标签1", "标签2"]
}
```

**注意**：`generated_articles_list` 里是纯 HTML 字符串，**标题分开存在 `article_titles` 里，按下标对应**。本平台会自动合并，不要自己拼。

### 3.4 验收报告 `report.json`

```json
{
  "client": "前海人寿保险股份有限公司",
  "client_short": "前海人寿",
  "article_count": 10,
  "batch_id": "20261104_105631",
  "batch_label": "投资实力首批",
  "rules_version": "0.1.0-draft",
  "evaluated_at": "2026-11-04 11:02",

  "summary": {
    "total": 330,              // 总判定项 = 篇数 × 参与判定的规则数
    "pass": 312,
    "violate": 9,
    "unclear": 9,              // 需外部资料或证据句对不上原文
    "hard_violate": 0,         // 其中拒稿级
    "judged": 321,
    "pass_rate_of_judged": 97.2
  },

  "articles": [
    {
      "index": 0,
      "title": "文章标题",
      "rows": [
        {
          "rule_id": "QIANHA-17",
          "statement": "不得与其他保险公司横向对比",
          "severity": "fix",
          "verdict": "violate",  // pass | violate | unclear
          "evidence": "近年收益表现位于同业前列、超越市场平均水平。",  // 原文逐字
          "reason": "使用了同业相对性评价",
          "method": "llm",       // code | llm
          "category": "stance",
          "category_label": "自我定位"
        }
      ]
    }
  ],

  "dedup": {
    "title_distinct": 6,           // 不同标题核心数
    "h2_overlap_max": 0.88,        // 章节骨架重合度最高值
    "h2_overlap_avg": 0.49,
    "sentence_reuse_ratio": 0.0,   // 跨篇逐字重复句占比
    "body_similarity_max": 0.32,
    "body_similarity_avg": 0.24,
    "warnings": ["章节骨架雷同：两篇 H2 主题重合度达 88%"]
  },

  "skipped": [
    {"id": "QIANHA-05", "statement": "...", "why": "prefer 类不进合格率"}
  ]
}
```

**判定语义**：

- `pass` 符合
- `violate` 违反，`evidence` 必须是原文中的**逐字句子**
- `unclear` 无法判定（需外部资料佐证，或模型给的证据句在原文中找不到）

**证据句校验是防伪机制**：模型判 violate 时必须粘贴原文原句；本平台会拿这句话回原文检索，**对不上就降级为 unclear**，不会算作违规。

### 3.5 批次目录

一个批次 = 一次验收，落盘结构：

```
clients/<slug>/batches/<batch_id>/
├── meta.json              批次元数据（名称/时间/文章数/违规数）
├── articles.json          上传的生文输出（原始）
├── rules_snapshot.yaml    本次评估用的规则包快照  ← 报告可回溯的关键
├── judge_tasks.json       发给模型的判定任务
├── judge_results.json     模型返回的判定
├── report.json            完整报告
└── board.html / board.pdf 看板（导出时生成）
```

**`rules_snapshot.yaml` 是设计要点**：保存当次使用的规则包副本。规则包后续变更不影响历史批次的结论，报告永远能回答「这份报告是按哪版规则判的」。

---

## 四、HTTP 接口

服务默认监听 `127.0.0.1:8901`（容器内 `0.0.0.0`）。

### 状态与列表

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/status` | 服务状态、模型配置、数据库连接 |
| GET | `/api/task` | 当前是否有重任务在跑 |
| GET | `/api/task/<id>` | 异步任务进度（`status` / `step` / `progress` / `result`） |
| GET | `/api/clients` | 客户列表（含规则数、批次数） |
| GET | `/api/batches/<slug>` | 某客户的批次列表 |
| GET | `/api/batch/<slug>/<batch_id>` | 单批次完整报告 |
| GET | `/api/rules/<slug>` | 规则包（评审页数据） |

### 写操作

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/upload` | 上传客户资料（multipart：`slug` `name` `short` `files`） |
| POST | `/api/extract` | 抽取规则 → **返回 202 + task_id** |
| POST | `/api/rules/<slug>/save` | 批量设置保留/移除（`{"kept": {"规则id": true/false}}`，false 走软删除） |
| POST | `/api/rules/<slug>/rule` | 新增或编辑一条规则（`{"mode":"create\|update","rule":{...}}`），仅允许模型判定类 |
| POST | `/api/rules/<slug>/rule/<id>/dismiss` | 软删除一条规则（保留记录，不再注入与判定） |
| POST | `/api/rules/<slug>/rule/<id>/restore` | 恢复一条软删除的规则 |
| POST | `/api/rules/<slug>/conflicts` | 保存冲突裁决（`{"conflicts":[{"topic","resolution","apply"}]}`） |
| POST | `/api/rules/<slug>/promote` | 确认转正：去掉版本号里的 `-draft` |
| POST | `/api/build/<slug>` | 生成定制工作流 yml |
| POST | `/api/evaluate` | 上传文章 JSON 评估 → **返回 202 + task_id** |

**所有规则写接口都会重建 `evaluate.py`**：评估器内嵌规则副本，不重建则新规则在验收时完全不生效。

### 下载

| 路径 | 说明 |
|---|---|
| `/api/download/<slug>/rules` | 下载规则包 |
| `/api/download/<slug>/workflow` | 下载定制工作流 yml |
| `/api/board/<slug>/<batch_id>` | 下载看板 HTML |
| `/api/board/<slug>/<batch_id>?format=pdf` | 下载看板 PDF |
| `/api/board/...?inline=1` | 浏览器内预览（不下载） |

### 异步任务说明

`/api/extract` 和 `/api/evaluate` 都要跑模型，耗时 3-8 分钟。**网关 60 秒会断连，所以必须异步**：

```bash
# 1. 发起
curl -X POST .../api/extract -H "Content-Type: application/json" -d '{"slug":"xxx"}'
# → {"ok":true,"task_id":"111953-5025","poll":"/api/task/111953-5025"}

# 2. 轮询
curl .../api/task/111953-5025
# → {"status":"running","step":"模型抽取规则（约 3-6 分钟）","progress":35}
# → {"status":"done","progress":100,"result":{...}}
```

前端已实现轮询 + 刷新后续跑（task_id 存 localStorage）。

**并发限制**：同一时间只允许一个重任务。第二个请求返回 409，并告知谁在跑。

---

## 五、部署

线上地址：**https://gen-workflow.ship.zhinao.qihoo.net**

### 环境变量

| 变量 | 说明 | 不配的后果 |
|---|---|---|
| `AI_PARSE_BASE_URL` | 模型接口地址 | 抽取/判定不可用 |
| `AI_PARSE_AUTHORIZATION` | 模型密钥（**必须含 `Bearer ` 前缀**） | 同上 |
| `AI_PARSE_MODEL` | 模型名，如 `openai/gpt-6.1-sol` | 同上 |
| `GW_DB_HOST` / `PORT` / `USER` / `PASSWORD` / `NAME` | MySQL 连接 | 降级为容器内 SQLite，重启丢数据 |
| `GEO_ALLOWED_HOSTS` | 允许的 Host，逗号分隔或 `*` | 非本机请求全部 403 |
| `GEO_CHROME` | Chromium 路径（PDF 用） | 看板只能导出 HTML |
| `GEO_TEMPLATE` | 母版 yml 路径 | 默认用镜像内 `assets/` |
| `GEO_BIND` / `--host` | 监听地址 | 容器内需 `0.0.0.0` |

### 数据持久化

**文件为工作区，数据库为持久层**：

- 写入：先落文件（现有逻辑不变）→ 同步数据库
- 启动：从数据库把文件还原回去（容器重启不丢数据）
- 读取：仍读文件

表全部 `gw_` 前缀，与 `kb_cleaning` 库原有表隔离：

| 表 | 内容 |
|---|---|
| `gw_client` | 客户 |
| `gw_client_asset` | 客户文件（原始资料/转出文本/规则包/初稿） |
| `gw_batch` | 批次索引（含违规数、合格率，可直接 SQL 统计） |
| `gw_batch_asset` | 批次文件（文章/报告/规则快照） |

数据库不可用时自动降级为纯文件模式，不影响功能。

### 部署命令

```bash
# 工具链不在系统 PATH（本机没有 Homebrew），每次发版先补路径
export PATH="$HOME/opt/lima/bin:$HOME/opt/bin:$HOME/opt/docker-cli:$HOME/opt/node/bin:$PATH"

# 构建（ARM Mac 必须指定平台，公司 K8s 是 amd64）
docker build --platform linux/amd64 -t gen-workflow:0.1.7 .

# 推送（版本号走 ship，不要用 latest）
ship registry push -r gen-workflow -s gen-workflow:0.1.7 --set-version 0.1.7 --project 1

# 部署（同名即滚动升级，VIP 与域名不变）
ship deploy create -n gen-workflow-test \
  -i harbor.qihoo.net/qsssre-zhinao-deploy/gen-workflow:0.1.7 \
  -p 8901 --project 1 -r 1 --cpu 1 --memory 2Gi \
  --skip-health-check --env GEO_ALLOWED_HOSTS=gen-workflow.ship.zhinao.qihoo.net
```

> colima 的 socket 由上面的 PATH 自动找到；若提示连不上，再补 `export DOCKER_HOST=unix://$HOME/.colima/default/docker.sock`。

---

## 六、代码结构

```
server.py                       HTTP 服务（路由、上传、异步任务）
db.py                           持久化层（MySQL/SQLite 双后端 + 文件同步）
Dockerfile                      镜像（python3.11 + chromium + 中文字体）
requirements.txt                PyYAML, PyMySQL
assets/通用生文工作流.yml          母版工作流（18 节点，随镜像分发）

scripts/
  extract_client_docs.py        docx/xlsx → 纯文本（保留段落边界）
  extract_rules.py              ★模型抽取规则（唯一调模型的抽取环节）
  draft_to_rules.py             初稿 → 规则包（schema 校验、detect 推导）
  rule_schema.py                ★schema 单一事实来源：枚举、校验、统计重算、软删除过滤
  build_client_workflow.py      规则包 → 定制 yml（注入 prompt + 代码门禁）
  gate_template.py              门禁代码模板（独立存放，避免 f-string 转义地狱）
  build_client_evaluator.py     规则包 → 评估器（代码可判 + 模型判定）
  run_judgement.py              ★批量执行模型判定
  export_board.py               报告 → 单文件 HTML 看板
  build_client.py               四步串联

report/
  upload.html + upload.js       导入客户资料
  rules/index.html + app.js     规则包评审
  index.html + app.js           验收报告（批次列表 + 报告详情）
  styles.css                    三页共用

clients/<slug>/                 各客户数据（不入镜像）
```

**`★` 标记的是会调用模型的两处**。其余全是确定性脚本，可复现。

---

## 七、已知限制

**抽取存在随机性**：同一批资料两次抽取结果不完全一致（约 20% 差异），关键风险项稳定覆盖，细节规则可能变动。这是因为一次调用要处理数万字资料、产出几十条规则。**规则包生成为 `0.1.0-draft` 就是提示需要人工评审。**

**只支持 18 节点能表达的需求**：换词包、加禁用词、改口吻、调结构偏好都可以；需要新增节点的（如独立的二次硬校验节点、竞品联网检索）走不了这条路。

**PDF 依赖 Chrome**：容器内装 chromium。在 ARM Mac 上用 QEMU 模拟 x86 跑 chromium 会因指令集报错，**集群真 amd64 正常**。

**交付流程类规则不执行**：`delivery` 类（如「须经法务审核」）只作清单展示，不注入 prompt 也不参与判定 —— 它们是流程约束，不是写作规则。

---

## 八、关键设计决策（供后续维护参考）

1. **拓扑冻结**：客户版工作流不增删节点。母版修 bug 后重跑脚本即可回灌所有客户，这是整个方案最大的收益。代价是放弃一部分定制自由度。

2. **文件 + 数据库双层**：没把 21 处文件读写全改成数据库，而是加一层同步。因为脚本要能在命令行直接跑，改成纯数据库会破坏这个能力。

3. **规则与知识库分离**：判断标准是「会随客户更新素材而失效的归知识库，描述表达禁区的归规则包」。这条边界决定了规则包里不该出现企业事实。

4. **判定结果必须带原文证据**：模型判违反时给不出能对上原文的句子，就降级为「无法判定」。宁可漏判，不可误判 —— 误判会让业务对报告失去信任。

5. **批次绑规则快照**：报告要能回答「按哪版规则判的」。规则包改了，历史报告结论不变。
