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
 "client": "异步测试",
 "code_rules": [
  {
   "id": "ASYNCT-29",
   "statement": "不得提及前海尊享安泰（2025c版）两全保险、前海尊享安泰（2025D版）两全保险及前海聚元宝（2025版C款）两全保险（分红型）",
   "severity": "fix",
   "polarity": "must_not",
   "detect": {
    "type": "product_names",
    "values": [
     "前海尊享安泰（2025c版）两全保险",
     "前海尊享安泰（2025D版）两全保险",
     "前海聚元宝（2025版C款）两全保险（分红型）"
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
   "id": "ASYNCT-01",
   "statement": "不得声称公司管理规则均已公开披露，或员工可随时查阅公开披露的全部制度文件",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "涉及员工关系、离职保障或公司内部管理制度",
   "scope": [
    "body"
   ],
   "scope_note": "管公司内部管理制度的公开性断言；不禁止依据已提供素材说明制度核实渠道。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-02",
   "statement": "不得将理赔处理时效与养老即时需求直接关联",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "讨论理赔时效与服务需求的关系",
   "scope": [
    "body"
   ],
   "scope_note": "管理赔时效与养老需求之间缺乏依据的关联；不禁止分别讨论理赔效率与养老服务。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-03",
   "statement": "不得编造素材未提供的公司政策、制度安排或服务细节",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "客户提供的素材没有相应内容",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "重点管培训、带教、入职体检、岗位限制等具体安排；不禁止对有依据的素材进行合理概括。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-04",
   "statement": "信息来源表述必须与实际披露情况一致，不得将官网未披露的内容归为企业官方披露",
   "severity": "fix",
   "polarity": "must",
   "condition": "说明信息来源或披露渠道",
   "scope": [
    "body"
   ],
   "scope_note": "管出处归属及披露渠道的真实性；不要求所有信息都必须来自官网，也不允许用模糊出处掩盖无依据内容。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-06",
   "statement": "不得使用容易被理解为公司官方澄清或公司已作回应的表述",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "文章并非公司官方声明，或没有公司回应的依据",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "管“官方澄清”“前海人寿回应”等身份与行为暗示；不禁止有真实依据的官方回应引用，也不禁止第三方疑问梳理。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-07",
   "statement": "必须分别标明各项数据的年份或统计截止时间，避免读者误认为属于同一统计期",
   "severity": "fix",
   "polarity": "must",
   "condition": "同一句或同一段使用不同年份、不同统计截止时间的数据",
   "scope": [
    "body"
   ],
   "scope_note": "管数据时间归属及跨期并列造成的歧义；不意味着标明年份后即可披露受限制的数据。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-08",
   "statement": "不得主动公开2025年的数据",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "涉及2025年数据",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "管以2025年为统计期或截止时间的数据主动披露；不等同于禁止出现“2025”年份文字或名称中带有2025的所有产品。原文未给出其他2025年数据的例外许可。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-10",
   "statement": "文章中必须删除前海智慧优选2026养老年金保险（分红型）及前海智慧优选2026A养老年金保险（分红型）的相关内容",
   "severity": "fix",
   "polarity": "must_not",
   "condition": null,
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "仅管原文指定的两款产品及其介绍内容；不自动扩大到其他养老年金保险或名称相近的产品。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-11",
   "statement": "监管机构应称为“国家金融监督管理总局”，不得在该当前监管语境中写成“银保监会”",
   "severity": "fix",
   "polarity": "must",
   "condition": "表述当前分红险产品定价监管机构或相关精算规定",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "管当前产品定价监管机构称谓；不据此禁止在准确的历史事件、旧文件名称或历史引用中出现“银保监会”。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-12",
   "statement": "必须区分官网某时点公开的在售产品数量与公司开业以来累计开发产品数量",
   "severity": "fix",
   "polarity": "must",
   "condition": "涉及产品数量",
   "scope": [
    "body"
   ],
   "scope_note": "管在售存量、累计开发量和统计时点的概念区分；不将原文中的具体数量固化为长期有效规则。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-13",
   "statement": "应表述为按照监管要求建设风险管理体系，而非与监管要求“高度适配”",
   "severity": "fix",
   "polarity": "must",
   "condition": "描述公司风险管理体系与监管要求的关系",
   "scope": [
    "body"
   ],
   "scope_note": "管风险管理体系的监管关系口径；不禁止介绍有依据的风险管理措施。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-14",
   "statement": "必须限定为“符合条件的保单客户”可享受相关权益，不得泛化到全部保单客户",
   "severity": "fix",
   "polarity": "must",
   "condition": "介绍医疗直付、养老社区入住等增值权益",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "管相关增值权益的客户适用范围；不要求将所有基础保险服务都附加相同限制。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-15",
   "statement": "不得将公司整体理赔数据或整体医养服务情况归为跨境养老服务",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "撰写跨境养老服务主题",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "管整体业务与跨境养老业务之间的归属嫁接；不禁止使用确属跨境养老且符合披露要求的专属素材。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-17",
   "statement": "必须补充展开素材中的具体服务内容，不得仅作概括性带过",
   "severity": "fix",
   "polarity": "must",
   "condition": "文章讨论线下网点、客服渠道或配套服务，且客户素材有对应具体内容",
   "scope": [
    "body"
   ],
   "scope_note": "管已有对应素材的展开程度；不要求无关文章强行加入全部服务内容，也不允许为展开而编造细节。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-18",
   "statement": "不得将医养业务表述为公司的核心业务",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "介绍公司业务定位",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "管医养业务的定位标签；不禁止介绍医养布局或“保险+医疗+养老”模式，也不据此推断其他未经说明的核心业务口径。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-19",
   "statement": "必须以对应公众号实际展示的功能为准，不能将不同官方公众号的功能混同",
   "severity": "fix",
   "polarity": "must",
   "condition": "介绍官方微信公众号及其服务功能",
   "scope": [
    "body"
   ],
   "scope_note": "管账号与功能的对应关系及“唯一官方服务公众号”等排他性误述；具体账号名录属于事实，不能据此假定各账号服务完全相同。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-20",
   "statement": "标题、首段和正文重点必须围绕同一主题展开，不能用无关内容替代标题承诺的分析",
   "severity": "fix",
   "polarity": "must",
   "condition": null,
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "管文题一致性，包括费用、投资实力、荣誉及合规等标题主题是否得到实质回应；不禁止与主题直接相关的背景介绍。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-21",
   "statement": "行业性主题必须在正文中充分展开，不得仅在首段点到后转为无关内容",
   "severity": "fix",
   "polarity": "must",
   "condition": "标题承诺行业性或多机构的信息梳理",
   "scope": [
    "body"
   ],
   "scope_note": "管行业主题的实际覆盖程度；不要求所有文章都采用行业视角或列举多家公司。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-22",
   "statement": "不得用无充分关联依据的业务布局、服务数据或资产配置描述强行论证产品稳健运营",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "说明产品运营支撑逻辑或建立业务之间的因果关系",
   "scope": [
    "body"
   ],
   "scope_note": "管论据与结论之间的牵强衔接；不全面禁止在产品文章中出现医养或投资内容，但必须说明有依据的相关性。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-23",
   "statement": "插入的信息必须与前后文论证连贯，不得突兀加入咨询渠道或参数句",
   "severity": "fix",
   "polarity": "must",
   "condition": "在产品分析中插入保费咨询、投保条件或产品参数",
   "scope": [
    "body"
   ],
   "scope_note": "管句间衔接与信息位置；不禁止说明官方咨询渠道，也不禁止引用经核实的具体产品参数。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-24",
   "statement": "不得硬造生词或将内部常用术语生硬拼接为公众文章表达",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "面向行业宣传或公众读者",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "管“内勤服务建设”等不自然、不常用的组合表达；不将“内勤”本身设为绝对禁用词，在确需解释内部岗位时仍应准确使用。",
   "needs_source": false
  },
  {
   "id": "ASYNCT-25",
   "statement": "不得拉踩同业，也不得通过明显失衡的信息展开制造前海人寿优势显著的比较印象",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "列举或比较多家保险公司",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "管贬损同业及比较材料失衡；不禁止客观列举多家公司，不要求所有公司机械使用相同字数，但比较维度应具有可比性。",
   "needs_source": false
  }
 ],
 "skipped": [
  {
   "id": "ASYNCT-05",
   "why": "may 类不进合格率",
   "statement": "允许使用“根据公开内容”等较宽泛的来源措辞"
  },
  {
   "id": "ASYNCT-09",
   "why": "prefer 类不进合格率",
   "statement": "非必要的数据尽量不使用"
  },
  {
   "id": "ASYNCT-16",
   "why": "prefer 类不进合格率",
   "statement": "尽量避免提及年报、经营数据、保费数据等相关词语和数据，也不要将其作为当前可公开核验的材料推荐"
  },
  {
   "id": "ASYNCT-26",
   "why": "prefer 类不进合格率",
   "statement": "避免将多个方面压缩成单段综述，应增加与主题相关的切入角度和具体展开"
  },
  {
   "id": "ASYNCT-27",
   "why": "prefer 类不进合格率",
   "statement": "适当增加与分析主题相关的具体产品参数，避免只有泛化介绍"
  },
  {
   "id": "ASYNCT-28",
   "why": "人工流程项",
   "statement": "稿件必须经过人工复核"
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
