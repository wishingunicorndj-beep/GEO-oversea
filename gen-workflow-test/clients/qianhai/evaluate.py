#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""客户质量评估器（由 build_client_evaluator.py 从规则包生成，勿手改）。

输入：生文输出 JSON（Dify end 节点返回体）
输出：验收报告（Markdown）+ 机器可读 JSON

判定分级：pass 符合 / violate 违反（evidence 为原文句子）/ unclear 无法判定
"""
import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher

SPEC = json.loads(r"""{
 "client": "HAIQIAN",
 "code_rules": [
  {
   "id": "QIANHA-04",
   "statement": "标题不得使用“热点回应”“极端场景”“投保决策参考”“可靠性验核标准”",
   "severity": "fix",
   "polarity": "must_not",
   "detect": {
    "type": "terms",
    "values": [
     "热点回应",
     "极端场景",
     "投保决策参考",
     "可靠性验核标准"
    ]
   },
   "scope": [
    "title"
   ]
  },
  {
   "id": "QIANHA-05",
   "statement": "该词条标题不得使用“坚持独立自主经营”",
   "severity": "fix",
   "polarity": "must_not",
   "detect": {
    "type": "terms",
    "values": [
     "坚持独立自主经营"
    ]
   },
   "scope": [
    "title"
   ]
  },
  {
   "id": "QIANHA-11",
   "statement": "不得使用“主流”“头部”“明星”等拔高前海人寿市场地位的表述",
   "severity": "fix",
   "polarity": "must_not",
   "detect": {
    "type": "terms",
    "values": [
     "主流",
     "头部",
     "明星"
    ]
   },
   "scope": [
    "title",
    "body"
   ]
  },
  {
   "id": "QIANHA-18",
   "statement": "不得使用“高分红”等夸大分红水平的表述",
   "severity": "fix",
   "polarity": "must_not",
   "detect": {
    "type": "terms",
    "values": [
     "高分红"
    ]
   },
   "scope": [
    "title",
    "body"
   ]
  },
  {
   "id": "QIANHA-41",
   "statement": "不得将已下架产品写入稿件，包括文件明确点名的“前海智慧优选”",
   "severity": "fix",
   "polarity": "must_not",
   "detect": {
    "type": "terms",
    "values": [
     "前海智慧优选"
    ]
   },
   "scope": [
    "title",
    "body"
   ]
  }
 ],
 "llm_rules": [
  {
   "id": "QIANHA-01",
   "statement": "标题中以“股东”代指“宝能集团”，弱化负面实体与品牌的直接关联",
   "severity": "fix",
   "polarity": "must",
   "condition": "股东债务危机等涉股东负面词条",
   "scope": [
    "title"
   ],
   "scope_note": "针对涉股东负面的标题实体处理，不等于正文禁提该实体；文件同时存在“必须隐去”和“尽量不提”两种强度，见 conflicts。",
   "needs_source": false
  },
  {
   "id": "QIANHA-03",
   "statement": "发稿表达须遵循低调原则，避免增加监管与舆情敏感度",
   "severity": "fix",
   "polarity": "must",
   "condition": "股东负面舆情相关内容的后续发稿",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "约束涉敏内容的表达与呈现方式，不等于禁止所有针对性澄清或必要的正文实体信息。",
   "needs_source": false
  },
  {
   "id": "QIANHA-06",
   "statement": "标题须从事件视角切换为服务视角，采用去情绪化、去事件化的中性表达",
   "severity": "fix",
   "polarity": "must",
   "condition": "保单业务、权益保障等服务指引类稿件",
   "scope": [
    "title"
   ],
   "scope_note": "主要针对服务指引类标题；不能自动扩大为债务危机词条也不得说明议题，文件对此存在范围歧义，见 conflicts。",
   "needs_source": false
  },
  {
   "id": "QIANHA-07",
   "statement": "标题与正文逻辑必须相符，不得出现严重脱节或文不对题",
   "severity": "reject",
   "polarity": "must",
   "condition": null,
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "直接拒稿针对严重的题文不符，不将普通措辞或局部细节问题自动升级为拒稿。",
   "needs_source": false
  },
  {
   "id": "QIANHA-08",
   "statement": "稿件不得存在大的业务逻辑错误",
   "severity": "reject",
   "polarity": "must_not",
   "condition": null,
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "针对影响文章成立的重大逻辑问题，不包括可由甲方直接修改的小细节。",
   "needs_source": false
  },
  {
   "id": "QIANHA-10",
   "statement": "不得将保险理赔与医养资源强行关联、作因果嫁接或暗示投保即绑定医养权益",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "涉及保险理赔与医养资源",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "禁止不当关联，不禁止两种业务在同篇中独立陈述或从实际行业角度同时讨论。",
   "needs_source": false
  },
  {
   "id": "QIANHA-12",
   "statement": "市场定位须采用“中小型险企”或“中等规模险企”的客观口径，并以前海人寿官网简介为对标依据",
   "severity": "fix",
   "polarity": "must",
   "condition": "确有必要描述前海人寿市场定位",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "限制必要定位时的写法，不要求每篇稿件主动增加规模定位。",
   "needs_source": false
  },
  {
   "id": "QIANHA-15",
   "statement": "稿件须聚焦前海人寿自身，不得进行同业拉踩、与其他保险公司的横向对比或信息盘点",
   "severity": "fix",
   "polarity": "must_not",
   "condition": null,
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "禁止跨公司比较与盘点，不等于禁止必要的行业背景；代表性机构列举许可的边界见 conflicts。",
   "needs_source": false
  },
  {
   "id": "QIANHA-16",
   "statement": "理赔内容仅围绕公司提供的理赔数据、科技赋能、特色理赔服务和真实案例展开",
   "severity": "fix",
   "polarity": "must",
   "condition": "理赔业务稿件或理赔业务段落",
   "scope": [
    "body"
   ],
   "scope_note": "限定理赔内容的展开范围，不把其他业务素材自动当作理赔能力依据。",
   "needs_source": false
  },
  {
   "id": "QIANHA-17",
   "statement": "不得超范围发挥、嫁接其他资源，或将行业通用服务包装为公司专属能力",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "描述理赔业务能力",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "禁止能力归属失真，不禁止如实描述有材料支持的公司服务。",
   "needs_source": false
  },
  {
   "id": "QIANHA-19",
   "statement": "必须明确区分“演示利率”与“红利实现率”，不得混为一谈",
   "severity": "fix",
   "polarity": "must",
   "condition": "分红险内容涉及演示利率或红利实现率",
   "scope": [
    "body"
   ],
   "scope_note": "要求区分概念与指标，不要求不涉及分红险的稿件增加这些内容。",
   "needs_source": false
  },
  {
   "id": "QIANHA-22",
   "statement": "须从法律层面区分股东与保险公司，按客户口径组织独立法人、不承担股东债务、保险保障基金及保单安全结论的论证",
   "severity": "fix",
   "polarity": "must",
   "condition": "股东债务危机类澄清内容",
   "scope": [
    "body"
   ],
   "scope_note": "管的是该类澄清稿的概念区分和指定论证口径，不将其中陈述抽取为适用于所有情形的独立企业事实；具体表述仍须走核实与合规审核流程。",
   "needs_source": false
  },
  {
   "id": "QIANHA-23",
   "statement": "须按客户指定口径明确说明“2022年免职决议未生效”和“董监高目前均在正常履职”",
   "severity": "fix",
   "polarity": "must",
   "condition": "针对管理层空缺传言进行澄清，且需要提及相关内容",
   "scope": [
    "body"
   ],
   "scope_note": "仅抽取针对性辟谣的必写口径，不视为其他词条应主动披露的事实；与高敏事项限制的适用关系须确认。",
   "needs_source": false
  },
  {
   "id": "QIANHA-24",
   "statement": "澄清类内容不得写成正规新闻稿或官方通稿体",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "负面舆情澄清内容",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "针对负面澄清的体裁与背书感，不等于禁止准确引用公开信息。",
   "needs_source": false
  },
  {
   "id": "QIANHA-25",
   "statement": "须使用第三方视角进行客观分析，降低官方背书感",
   "severity": "fix",
   "polarity": "must",
   "condition": "股东债务危机等负面舆情澄清内容",
   "scope": [
    "body"
   ],
   "scope_note": "约束叙述视角，不授权虚构第三方意见或伪造引用来源。",
   "needs_source": false
  },
  {
   "id": "QIANHA-28",
   "statement": "须充分展开已提供的相关素材，提高素材覆盖率，避免仅使用少量素材",
   "severity": "fix",
   "polarity": "must",
   "condition": "已提供相关写作素材",
   "scope": [
    "body"
   ],
   "scope_note": "要求提高相关素材的展开度，不等于无条件纳入全部素材；禁止、受限或核不出的内容仍受相应规则约束。",
   "needs_source": false
  },
  {
   "id": "QIANHA-43",
   "statement": "无关词条不得主动提及董监高",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "词条不涉及董监高",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "限制主动披露，不等于相关词条也一律禁提；管理层空缺类澄清如何适用须向甲方确认。",
   "needs_source": false
  }
 ],
 "skipped": [
  {
   "id": "QIANHA-02",
   "why": "may 类不进合格率",
   "statement": "正文可适度提及“宝能集团”，以保留必要的实体信息"
  },
  {
   "id": "QIANHA-09",
   "why": "may 类不进合格率",
   "statement": "允许不同业务同时输出，但须结合实际情况从行业角度表述"
  },
  {
   "id": "QIANHA-13",
   "why": "prefer 类不进合格率",
   "statement": "非必要不主动输出前海人寿的中小型或中等规模定位"
  },
  {
   "id": "QIANHA-14",
   "why": "may 类不进合格率",
   "statement": "可将前海人寿表述为“有代表性的机构”或必要情况下的“其中之一”"
  },
  {
   "id": "QIANHA-20",
   "why": "may 类不进合格率",
   "statement": "可补充说明相关数据为动态更新"
  },
  {
   "id": "QIANHA-21",
   "why": "may 类不进合格率",
   "statement": "可在如实承接材料前提和上下文后使用“大部分产品红利实现率超过100%”这一表述"
  },
  {
   "id": "QIANHA-26",
   "why": "prefer 类不进合格率",
   "statement": "建议采用第三方自媒体、大V或论坛帖子的客观分析体裁"
  },
  {
   "id": "QIANHA-27",
   "why": "prefer 类不进合格率",
   "statement": "建议沿用股权、经营、保单三个维度展开，并跳过非必要细节直接切入核心议题"
  },
  {
   "id": "QIANHA-29",
   "why": "人工流程项",
   "statement": "稿件产出必须加入人工把控环节，不得完全依赖机器生成"
  },
  {
   "id": "QIANHA-30",
   "why": "人工流程项",
   "statement": "稿件须依次经过编辑室、相关领导、法务合规和消费者权益保护中心四道审核"
  },
  {
   "id": "QIANHA-31",
   "why": "人工流程项",
   "statement": "产品购买类稿件的具体用语须额外提交合规消保部门审查，不能仅凭结构通过或编辑判断定稿"
  },
  {
   "id": "QIANHA-32",
   "why": "人工流程项",
   "statement": "语料须经前海人寿审核同意后方可投放"
  },
  {
   "id": "QIANHA-33",
   "why": "人工流程项",
   "statement": "先提交各词条标题与文章架构供甲方确认，确认后再产出5篇以内人工稿件"
  },
  {
   "id": "QIANHA-34",
   "why": "人工流程项",
   "statement": "须对提供素材进行官方或第三方机构核实，并将核实结果提前反馈甲方"
  },
  {
   "id": "QIANHA-35",
   "why": "人工流程项",
   "statement": "须提前向甲方主动上报核不出的素材及无法表述的内容，不得硬写"
  },
  {
   "id": "QIANHA-36",
   "why": "人工流程项",
   "statement": "后续以达标新稿为生产标准，旧稿作废"
  },
  {
   "id": "QIANHA-37",
   "why": "人工流程项",
   "statement": "按甲方直接修改后反馈的方式处理，不因小细节问题推翻整篇或要求整篇返工"
  },
  {
   "id": "QIANHA-38",
   "why": "人工流程项",
   "statement": "乙方须主动学习并掌握金融及保险行业术语，不得完全依赖甲方逐条纠正"
  },
  {
   "id": "QIANHA-39",
   "why": "人工流程项",
   "statement": "须将会议行业术语、业务逻辑和合规要求整理成文字版，供模型训练与人工编辑参考"
  },
  {
   "id": "QIANHA-40",
   "why": "人工流程项",
   "statement": "须梳理行业及平台侧禁止或受限表述清单，并同步甲方"
  },
  {
   "id": "QIANHA-42",
   "why": "人工流程项",
   "statement": "须将偿付能力、风险综合评级和董监高内容识别为高敏受限事项，按甲方口径审核处理"
  },
  {
   "id": "QIANHA-44",
   "why": "may 类不进合格率",
   "statement": "相关词条可呈现董监高内容"
  },
  {
   "id": "QIANHA-45",
   "why": "人工流程项",
   "statement": "董监高表述须严格按照更新后的材料撰写"
  }
 ]
}""")

# 标题同质判定阈值
TITLE_DUP_WARN = 0.5      # 不同标题核心占比低于此值告警
H2_OVERLAP_WARN = 0.7     # 两篇 H2 主题重合度高于此值告警
SENT_REUSE_WARN = 0.15    # 跨篇复用句占比高于此值告警


def _text(v):
    return '' if v is None else str(v)


def _strip_tags(html):
    t = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', _text(html), flags=re.S | re.I)
    t = re.sub(r'<[^>]+>', '\n', t)
    return re.sub(r'\n{2,}', '\n', t).strip()


def _parse_article(raw):
    if isinstance(raw, dict):
        return dict(raw)
    t = _text(raw).strip()
    if t.startswith('```'):
        t = re.sub(r'^```(?:json)?\s*', '', t, flags=re.I)
        t = re.sub(r'\s*```$', '', t)
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        m = re.search(r'\{.*\}', t, flags=re.S)
        if not m:
            return {}
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}


def _fields(art):
    title = _text(art.get('title') or art.get('headline'))
    content = _text(art.get('content') or art.get('body'))
    body = _strip_tags(content)
    desc = _text(art.get('description') or art.get('meta_description'))
    tags = art.get('tags')
    if isinstance(tags, list):
        tags = ' '.join(_text(x) for x in tags)
    return {'title': title, 'body': body, 'content': content,
            'description': desc, 'tags': _text(tags)}


# ---------------------------------------------------------------------------
# 确定性检查
# ---------------------------------------------------------------------------
def _snip(text, start, end, pad=24):
    left = max(0, start - pad)
    right = min(len(text), end + pad)
    pre = text[left:start]
    for sep in ('。', '！', '？', '；', '\n'):
        k = pre.rfind(sep)
        if k >= 0:
            left = left + k + 1
            break
    post = text[end:right]
    for sep in ('。', '！', '？', '；', '\n'):
        k = post.find(sep)
        if k >= 0:
            right = end + k + 1
            break
    return text[left:right].replace('\n', ' ').strip()


def check_code_rule(rule, fields):
    det = rule.get('detect') or {}
    dtype = det.get('type')
    values = det.get('values') or []
    scope = rule.get('scope') or ['title', 'body']
    targets = [(k, fields[k]) for k in ('title', 'body') if k in scope and fields.get(k)]

    if dtype in ('terms', 'product_names'):
        for fname, text in targets:
            for v in values:
                if v and v in text:
                    idx = text.find(v)
                    return 'violate', _snip(text, idx, idx + len(v)), '%s出现「%s」' % (fname, v)
        return 'pass', '', ''

    if dtype == 'regex':
        for fname, text in targets:
            for p in values:
                try:
                    m = re.search(p, text)
                except re.error:
                    continue
                if m:
                    return 'violate', _snip(text, m.start(), m.end()), '%s命中模式' % fname
        return 'pass', '', ''

    return 'unclear', '', '未支持的 detect 类型'


# ---------------------------------------------------------------------------
# 模型判定：一篇文章一次调用，批量覆盖多条规则
# ---------------------------------------------------------------------------
def build_llm_tasks(articles, chunk_size=20):
    """返回 [{"article_index":i, "rule_ids":[...], "prompt":"..."}]"""
    tasks = []
    for i, raw in enumerate(articles):
        art = _parse_article(raw) if not isinstance(raw, dict) else raw
        f = _fields(art)
        rules = SPEC['llm_rules']
        for start in range(0, len(rules), chunk_size):
            group = rules[start:start + chunk_size]
            tasks.append({
                'article_index': i,
                'rule_ids': [r['id'] for r in group],
                'prompt': _group_prompt(f, group),
                'expect': '[{"rule_id":"...","verdict":"pass|violate|unclear","evidence":"","reason":""}]',
            })
    return tasks


def _group_prompt(fields, group):
    lines = []
    lines.append('你是内容合规审核员。下面给出若干条独立的审核规则，请逐条判断本文是否违反。')
    lines.append('')
    lines.append('【文章标题】')
    lines.append(fields['title'])
    lines.append('')
    lines.append('【文章正文】')
    lines.append(fields['body'])
    lines.append('')
    lines.append('【审核规则】')
    for r in group:
        head = '- %s：%s' % (r['id'], r['statement'])
        if r.get('condition'):
            head += '（适用条件：%s）' % r['condition']
        lines.append(head)
        if r.get('scope_note'):
            for ln in r['scope_note'].split('\n'):
                if ln.strip():
                    lines.append('  ' + ln.strip())
    lines.append('')
    lines.append('【判定要求】')
    lines.append('1. 每条规则独立判断，互不影响；只依据规则原文，不引入其他标准。')
    lines.append('2. 判为 violate 时，evidence 必须从【文章标题】或【文章正文】中逐字复制一句原文，不得改写、不得拼接。')
    lines.append('3. 找不到可逐字复制的原文句子，说明证据不足，verdict 填 unclear。')
    lines.append('4. 规则未涉及本文主题时（如规则只针对分红险而本文不涉及），verdict 填 pass。')
    lines.append('5. 文章中对某问题的否定式表述（如「不应理解为…」「不建议只看…」）不构成违反。')
    lines.append('')
    lines.append('【输出】只输出 JSON 数组，每条规则一个对象，顺序与上方规则一致：')
    lines.append('[{"rule_id":"规则ID","verdict":"pass|violate|unclear","evidence":"","reason":"一句话"}]')
    return '\n\n'.join(lines)


def verify_evidence(verdict, evidence, fields):
    """证据句必须能在原文逐字找到，否则降级 unclear。"""
    if verdict != 'violate':
        return verdict
    ev = _text(evidence).strip()
    if not ev:
        return 'unclear'
    haystack = fields['title'] + '\n' + fields['body']
    norm = lambda s: re.sub(r'\s+', '', s)
    return 'violate' if norm(ev) in norm(haystack) else 'unclear'


# ---------------------------------------------------------------------------
# 整批重复度（纯代码，可复现）
# ---------------------------------------------------------------------------
H2_TOPICS = ['结论', '定位', '资质', '团队', '策略', '布局', '配置', '表现',
             '红利', '核验', '判断', '维度', '适合', '边界', '误区', '行动']


def _title_core(title):
    return re.sub(r'[：:（(].*$', '', _text(title)).strip()


def _h2_list(content):
    hs = re.findall(r'<h2[^>]*>(.*?)</h2>', _text(content), re.S | re.I)
    return [re.sub(r'<[^>]+>', '', h).strip() for h in hs]


def _h2_signature(h2s):
    sig = []
    for h in h2s:
        key = next((k for k in H2_TOPICS if k in h), '其他')
        sig.append(key)
    return sig


def _sentences(text):
    return [s.strip() for s in re.split(r'[。！？\n]', text) if len(s.strip()) >= 15]


def batch_metrics(articles):
    arts = [_parse_article(a) if not isinstance(a, dict) else a for a in articles]
    fields = [_fields(a) for a in arts]
    titles = [f['title'] for f in fields]
    bodies = [f['body'] for f in fields]
    h2s = [_h2_list(a.get('content') or '') for a in arts]

    cores = [_title_core(t) for t in titles]
    core_counts = Counter(c for c in cores if c)

    pairs = []
    for i in range(len(h2s)):
        for j in range(i + 1, len(h2s)):
            a, b = set(_h2_signature(h2s[i])), set(_h2_signature(h2s[j]))
            if not a or not b:
                continue
            pairs.append(len(a & b) / float(len(a | b)))

    sent_counts = Counter()
    for b in bodies:
        for s in set(_sentences(b)):
            sent_counts[s] += 1
    reused = [s for s, n in sent_counts.items() if n >= 2]
    reuse_ratio = sum(sent_counts[s] for s in reused) / float(max(1, sum(len(_sentences(b)) for b in bodies)))

    sims = []
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            sims.append(SequenceMatcher(None, bodies[i], bodies[j]).ratio())

    sigs = [_h2_signature(h) for h in h2s]
    common = Counter()
    for s in sigs:
        common.update(set(s))
    dominant = [k for k, n in common.items() if n >= max(2, len(articles) * 0.8)]

    return {
        'article_count': len(articles),
        'title_distinct': len(set(c for c in cores if c)),
        'title_duplicate_top': [{'core': c, 'count': n} for c, n in core_counts.most_common(3)],
        'h2_overlap_avg': round(sum(pairs) / len(pairs), 3) if pairs else 0.0,
        'h2_overlap_max': round(max(pairs), 3) if pairs else 0.0,
        'dominant_topics': dominant,
        'sentence_reuse_ratio': round(reuse_ratio, 3),
        'body_similarity_avg': round(sum(sims) / len(sims), 3) if sims else 0.0,
        'body_similarity_max': round(max(sims), 3) if sims else 0.0,
        'warnings': _dup_warnings(len(articles), len(set(c for c in cores if c)),
                                  max(pairs) if pairs else 0.0, reuse_ratio, dominant),
    }


def _dup_warnings(n, distinct, h2_max, reuse, dominant):
    w = []
    if n >= 3 and distinct / float(n) < TITLE_DUP_WARN:
        w.append('标题同质：%d 篇只有 %d 个不同核心' % (n, distinct))
    if h2_max >= H2_OVERLAP_WARN:
        w.append('章节骨架雷同：两篇 H2 主题重合度达 %.0f%%' % (h2_max * 100))
    if reuse >= SENT_REUSE_WARN:
        w.append('句子复用：%.0f%% 的句子在其他篇也出现' % (reuse * 100))
    if dominant:
        w.append('固定套路：%s 出现在 80%% 以上的篇目中' % '、'.join(dominant))
    return w


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------
def evaluate(articles, llm_results=None):
    """llm_results: [{"article_index":i,"rule_id":"...","verdict":"...","evidence":"...","reason":"..."}]"""
    idx = {}
    for r in (llm_results or []):
        idx[(r.get('article_index'), r.get('rule_id'))] = r

    out = []
    for i, raw in enumerate(articles):
        art = _parse_article(raw) if not isinstance(raw, dict) else raw
        f = _fields(art)
        rows = []
        for rule in SPEC['code_rules']:
            v, ev, reason = check_code_rule(rule, f)
            rows.append({'rule_id': rule['id'], 'statement': rule['statement'],
                         'severity': rule.get('severity'), 'verdict': v,
                         'evidence': ev, 'reason': reason, 'method': 'code'})
        for rule in SPEC['llm_rules']:
            got = idx.get((i, rule['id'])) or {}
            v = got.get('verdict') or 'unclear'
            ev = _text(got.get('evidence'))
            v2 = verify_evidence(v, ev, f)
            rows.append({'rule_id': rule['id'], 'statement': rule['statement'],
                         'severity': rule.get('severity'), 'verdict': v2,
                         'evidence': ev if v2 == 'violate' else '',
                         'reason': got.get('reason') or ('证据句对不上原文' if got else '未执行模型判定'),
                         'method': 'llm'})
        out.append({'index': i, 'title': f['title'], 'rows': rows})

    judged = [r for a in out for r in a['rows']]
    return {
        'client': SPEC['client'],
        'article_count': len(out),
        'articles': out,
        'skipped': SPEC['skipped'],
        'summary': summarize(judged),
        'dedup': batch_metrics(articles),
    }


def summarize(rows):
    total = len(rows)
    v = sum(1 for r in rows if r['verdict'] == 'violate')
    u = sum(1 for r in rows if r['verdict'] == 'unclear')
    p = total - v - u
    hard = sum(1 for r in rows if r['verdict'] == 'violate' and r.get('severity') == 'reject')
    return {'total': total, 'pass': p, 'violate': v, 'unclear': u,
            'hard_violate': hard,
            'judged': total - u,
            'pass_rate_of_judged': round(p / (total - u) * 100, 1) if total - u else 0.0}


def to_markdown(report):
    s = report['summary']
    d = report['dedup']
    lines = ['# %s 生文质量验收报告' % report['client'], '']
    lines.append('整批 %d 篇。规则判定 %d 项：符合 %d，违反 %d（拒稿级 %d），无法判定 %d。'
                 % (report['article_count'], s['total'], s['pass'], s['violate'],
                    s['hard_violate'], s['unclear']))
    if s['judged']:
        lines.append('')
        lines.append('已判定 %d 项中合格率 %.1f%%。' % (s['judged'], s['pass_rate_of_judged']))
    lines.append('')
    lines.append('## 整批重复度')
    lines.append('')
    lines.append('| 指标 | 数值 |')
    lines.append('|---|---|')
    lines.append('| 不同标题核心 | %d / %d 篇 |' % (d['title_distinct'], d['article_count']))
    lines.append('| H2 主题重合度（最高 / 平均） | %.0f%% / %.0f%% |' % (d['h2_overlap_max'] * 100, d['h2_overlap_avg'] * 100))
    lines.append('| 跨篇句子复用率 | %.0f%% |' % (d['sentence_reuse_ratio'] * 100))
    lines.append('| 正文两两相似度（最高 / 平均） | %.0f%% / %.0f%% |' % (d['body_similarity_max'] * 100, d['body_similarity_avg'] * 100))
    lines.append('')
    if d['warnings']:
        lines.append('**重复度告警：**')
        for w in d['warnings']:
            lines.append('- ' + w)
    else:
        lines.append('重复度未见异常。')
    lines.append('')
    for art in report['articles']:
        lines.append('## 第 %d 篇：%s' % (art['index'] + 1, art['title'][:40]))
        lines.append('')
        lines.append('| 客户要求 | 判定 | 证据（原文） |')
        lines.append('|---|---|---|')
        for row in art['rows']:
            mark = {'pass': '符合', 'violate': '**违反**', 'unclear': '无法判定'}[row['verdict']]
            ev = row['evidence'].replace('|', '\\|')[:80]
            lines.append('| %s %s | %s | %s |' % (row['rule_id'], row['statement'][:44], mark, ev or '—'))
        lines.append('')
    if report.get('skipped'):
        lines.append('## 未纳入合格率的规则')
        lines.append('')
        for sk in report['skipped']:
            lines.append('- %s：%s（%s）' % (sk['id'], sk['statement'][:50], sk['why']))
    return '\n'.join(lines)


def evaluate_file(path, llm_results=None):
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    arts = data.get('generated_articles_list') or data.get('articles') or []
    titles = data.get('article_titles') or []
    merged = []
    for i, a in enumerate(arts):
        if isinstance(a, str) and not a.lstrip().startswith('{'):
            merged.append({'title': titles[i] if i < len(titles) else '', 'content': a})
        else:
            merged.append(a)
    return evaluate(merged, llm_results)


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        print('用法: evaluate.py <生文输出.json> [llm_results.json]')
        sys.exit(1)
    llm = None
    if len(args) > 1:
        with open(args[1], encoding='utf-8') as fh:
            llm = json.load(fh)
    print(to_markdown(evaluate_file(args[0], llm)))
