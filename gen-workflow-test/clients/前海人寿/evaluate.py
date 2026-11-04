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
 "client": "前海人寿保险股份有限公司",
 "code_rules": [
  {
   "id": "QH-P01",
   "statement": "不得用拔高市场地位的词汇描述本公司或同业",
   "severity": "reject",
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
   "id": "QH-P02",
   "statement": "不得用「高分红」等夸大表述描述分红水平",
   "severity": "reject",
   "polarity": "must_not",
   "detect": {
    "type": "terms",
    "values": [
     "高分红"
    ]
   },
   "scope": [
    "body"
   ]
  },
  {
   "id": "QH-P03",
   "statement": "标题不得使用涉敏或不合行业规范的表述",
   "severity": "reject",
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
   "id": "QH-P04",
   "statement": "不得写入客户已下架或明示不提的产品",
   "severity": "reject",
   "polarity": "must_not",
   "detect": {
    "type": "product_names",
    "values": [
     "前海智慧优选2026养老年金保险（分红型）",
     "前海智慧优选2026A养老年金保险（分红型）",
     "前海尊享安泰（2025C版）两全保险",
     "前海尊享安泰（2025D版）两全保险",
     "前海聚元宝（2025版C款）两全保险（分红型）"
    ]
   },
   "scope": [
    "body"
   ]
  },
  {
   "id": "QH-I01",
   "statement": "标题中不得直书股东实体名称「宝能集团」，用「股东」代指",
   "severity": "reject",
   "polarity": "must",
   "detect": {
    "type": "terms",
    "values": [
     "宝能集团"
    ]
   },
   "scope": [
    "title"
   ]
  }
 ],
 "llm_rules": [
  {
   "id": "QH-P05",
   "statement": "不得将本公司与同业做横向对比或信息盘点",
   "severity": "reject",
   "polarity": "must_not",
   "condition": null,
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "本规则只禁止两种写法：①明确拿本公司与某家或某类同业比较高低优劣；②罗列多家同业的优劣信息做盘点。\n不构成违反的情形：\n- 只描述本公司自身情况，未与其他机构对照（如「前海人寿成立于2012年」「公司注册资本85亿元」）。\n- 说明行业通用逻辑或一般性判断框架（如「寿险公司通常更强调长期稳健」），未指向具体同业作比较。\n- 引用监管口径、行业标准时提及同业整体，但未评价本公司相对高低。\n- 本公司规模的客观定位（如「属于中等规模寿险公司」）未与具体同业比高低时，不判违反。\n明确构成违反的措辞：「位于同业前列」「超越市场平均水平」「优于同业」「行业第一」「主流机构」等相对性评价。\n不构成违反的情形（补充）：FAQ 或小标题中以设问形式出现上述措辞、且正文未作肯定断言时，不判违反（如「收益表现位于同业前列有公开数据吗？」是在质疑该说法，不是采用它）。",
   "needs_source": false
  },
  {
   "id": "QH-P06",
   "statement": "不得主动提及公司偿付能力、风险综合评级、董监高（澄清类词条例外，见 QH-F05）",
   "severity": "fix",
   "polarity": "must_not",
   "condition": null,
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "本规则只针对三类敏感信息：偿付能力充足率/偿付能力报告、风险综合评级、董监高人员信息。\n不构成违反的情形：\n- 提到「资产负债管理」「风险管理体系」「监管指标约束」等泛化表述而未点出偿付能力具体指标。\n- 医学、金融业的通用词「风险」出现在其他语境（如「投资风险」「市场风险」）。\n判为违反需句中确实出现「偿付能力」「风险综合评级」「董监高」「高管履职」等具体指向。\n若本文属于管理层/股东相关澄清类词条，第 QH-F05 条适用，本规则不重复判定。",
   "needs_source": false
  },
  {
   "id": "QH-F01",
   "statement": "必须明确区分「演示利率」与「红利实现率」，二者不得混为一谈",
   "severity": "fix",
   "polarity": "must",
   "condition": "分红险相关词条",
   "scope": [
    "body"
   ],
   "scope_note": "本规则只针对分红险相关词条，且只要求「演示利率」与「红利实现率」两个概念不被混用。\n不构成违反的情形：\n- 两个概念均未出现。\n- 两个概念分别出现且各自解释正确。\n- 使用「演示水平」「利益演示」指代演示利率一侧时，只要未与红利实现率混为一谈，不判违反。\n明确构成违反：把红利实现率解释成收益率、把演示利率说成实际收益、把两者当作同一个指标。\n注意：本文不涉及分红险时，直接输出 pass。",
   "needs_source": false
  },
  {
   "id": "QH-F03",
   "statement": "表述为「按监管要求」建立体系，不得写成「与监管要求高度适配」",
   "severity": "fix",
   "polarity": "must",
   "condition": "涉及公司治理风险、监管关系",
   "scope": [
    "body"
   ],
   "scope_note": "本规则只针对描述公司治理体系与监管关系的表述，且只纠正一种措辞：把「按监管要求建立」写成「与监管要求高度适配」。\n不构成违反的情形：\n- 未涉及公司治理或监管关系。\n- 写成「按监管要求」「依照监管规定」「在监管框架下」等符合原意的表述。\n- 「符合监管要求」这类常规表述不判违反，除非同时出现「高度适配」「完全契合」等拔高措辞。",
   "needs_source": false
  },
  {
   "id": "QH-F04",
   "statement": "医养是特色布局，不得表述为公司的「核心业务」",
   "severity": "fix",
   "polarity": "must",
   "condition": "涉及医养定位",
   "scope": [
    "body"
   ],
   "scope_note": "本规则只禁止把医养业务称为公司的「核心业务」。\n不构成违反的情形：\n- 把医养表述为「特色布局」「特色产业」「业务之一」「战略布局」。\n- 未提及医养业务。\n- 提到「保险主业」时讨论的是保险而非医养。\n判为违反需文中明确把医养写成「核心业务」或同等地位的表述（如「以医养为核心」）。",
   "needs_source": false
  },
  {
   "id": "QH-C02",
   "statement": "不得将保险理赔与医养资源做因果嫁接，不得把医养权益写成保单的附加价值或投保绑定项",
   "severity": "reject",
   "polarity": "must_not",
   "condition": null,
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "本规则只禁止一种关联：把医养资源写成保单的附加权益、投保绑定项、或「买保险就能享受医养」的因果表述。\n不构成违反的情形：\n- 把医养作为独立的机构能力或产业布局陈述（如「旗下在营多家三级医院」）。\n- 明确说明医养与保险是两个独立业务。\n- 说明「符合条件的保单客户可享受相关权益」——这是加了限定的合规表述，不判违反。\n判为违反需出现「保障之外还能兑现」「投保即享」「保单附带医养权益」这类把两者绑定的写法。",
   "needs_source": false
  },
  {
   "id": "QH-V01",
   "statement": "不得写成新闻通稿体或官方声明体",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "负面舆情/经营稳健性澄清类词条",
   "scope": [
    "body"
   ],
   "scope_note": "本规则只针对澄清类词条，且只禁止「新闻通稿体/官方声明体」这一种文风。\n不构成违反的情形：\n- 本文不属于澄清类词条（如产品介绍、投资实力核验），直接输出 pass。\n- 采用第三方分析口吻、带「从公开信息来看」「有分析认为」等标记。\n- 客观说明文，即使语气正式，只要不是通稿体或声明体，不判违反。",
   "needs_source": false
  },
  {
   "id": "QH-V02",
   "statement": "标题不得停留在事件视角，须转为服务视角",
   "severity": "fix",
   "polarity": "must_not",
   "condition": null,
   "scope": [
    "title"
   ],
   "scope_note": "本规则只针对标题，且只禁止「事件视角」——即把标题写成对某个事件、舆情、危机的回应或解释。\n不构成违反的情形：\n- 标题是服务指引型（如「投保指南」「办理路径」「核验清单」）。\n- 标题是客观说明型（如「前海人寿投资实力如何」）。\n判为违反需标题出现「回应」「澄清」「事件」「危机」「爆雷」「极端场景」等事件化措辞。",
   "needs_source": false
  },
  {
   "id": "QH-V03",
   "statement": "避免使用评价性、推销性标题",
   "severity": "advise",
   "polarity": "must_not",
   "condition": null,
   "scope": [
    "title"
   ],
   "scope_note": "本规则只针对标题，且只禁止明显的评价性、推销性表述。\n不构成违反的情形：\n- 标题是中性问句（如「前海人寿怎么样」「值得买吗」这类用户常见搜索词）。\n- 标题是核验、指南、清单类表述。\n判为违反需标题出现直接推荐购买、保证收益、绝对化评价（如「最好的选择」「必买」）。",
   "needs_source": false
  },
  {
   "id": "QH-V04",
   "statement": "不得硬造行业生词",
   "severity": "advise",
   "polarity": "must_not",
   "condition": null,
   "scope": [
    "body"
   ],
   "scope_note": "本规则只禁止自创的、非行业通用的生造词（如「内勤服务建设」这类把内部行话直接搬入宣传语的写法）。\n不构成违反的情形：\n- 使用金融、保险行业的标准术语（偿付能力、红利实现率、资产负债管理）。\n- 使用通用商业词汇（生态、矩阵、闭环）——即使略显空泛，也不判为本规则违反。\n判为违反需该词在保险行业公开语境中基本不出现，且含义需要读者猜测。",
   "needs_source": false
  },
  {
   "id": "QH-T01",
   "statement": "标题与正文主题必须一致；标题承诺的内容必须在正文兑现",
   "severity": "reject",
   "polarity": "must",
   "condition": null,
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "本规则判断标题承诺的内容是否在正文兑现，以及全文主题是否与标题一致。\n不构成违反的情形：\n- 正文首段即回扣标题主体，后续章节围绕标题展开。\n- 标题为设问句而正文给出回答。\n判为违反需出现：标题问 A 而正文主要讲 B；标题承诺列举 N 项而正文未列；标题的关键概念在正文中缺位。",
   "needs_source": false
  },
  {
   "id": "QH-T04",
   "statement": "必须形成完整逻辑链：保险公司是独立法人不承担股东债务 → 有保险保障基金兜底 → 保单安全",
   "severity": "fix",
   "polarity": "must",
   "condition": "股东债务不影响经营类澄清",
   "scope": [
    "body"
   ],
   "scope_note": "本规则只针对股东债务相关的澄清类词条，要求形成完整逻辑链。\n不构成违反的情形：\n- 本文不涉及股东债务或经营稳健性澄清，直接输出 pass。\n- 逻辑链已完整：法人独立 → 保险保障基金兜底 → 保单安全。\n- 分多处陈述但三要素齐全，不要求出现在同一段落。",
   "needs_source": false
  },
  {
   "id": "QH-T06",
   "statement": "避免通篇单一综述式写法，需多切入角度",
   "severity": "advise",
   "polarity": "must_not",
   "condition": null,
   "scope": [
    "body"
   ],
   "scope_note": "本规则只禁止通篇只有单一综述式写法（全文一段到底、只做泛泛概括、无分节维度）。\n不构成违反的情形：\n- 文章有多个 H2 分节，各节切入角度不同。\n- 分节虽同为主题的不同侧面（如资质、团队、策略），只要各有实质内容，不判违反。\n判为违反需全文缺乏分节，或各节内容高度重复、无新的信息增量。",
   "needs_source": false
  },
  {
   "id": "QH-D01",
   "statement": "不同年份的数据不得放在同一句中，引用任一数据须标注其所属年份",
   "severity": "fix",
   "polarity": "must",
   "condition": null,
   "scope": [
    "body"
   ],
   "scope_note": "本规则只针对一种错误：把分属不同年份的数据放在同一句里，让读者误以为是同期数据。\n不构成违反的情形：\n- 数据未标注年份但只是一句话描述公司现状（如「注册资本85亿元」）——本规则不要求给所有数据补年份。\n- 同一年份的多个数据同句。\n- 不同年份的数据分句陈述，各自标明年份。\n判为违反需同一句中同时出现两个及以上不同年份标记的数据，且未作区分说明。",
   "needs_source": false
  },
  {
   "id": "QH-D03",
   "statement": "公司目前暂停披露年报，避免提及年报、经营数据、保费数据",
   "severity": "reject",
   "polarity": "must_not",
   "condition": null,
   "scope": [
    "body"
   ],
   "scope_note": "本规则只针对三类披露文件与数据：年度报告、保费收入、经营收入。\n不构成本规则范围（不要判违反）：\n- 投资金额、投资面积、项目数量、不动产规模。\n- 团队人数、专业资格人数。\n- 客户数量、服务人次。\n- 产品数量、产品款数。\n- 注册资本、成立时间。\n判为违反需文中明确出现「年报」「年度报告」「保费收入」「保费规模」「营业收入」「经营收入」。",
   "needs_source": false
  },
  {
   "id": "QH-D04",
   "statement": "须说明口径为官网当期在售数量，不得写成累计开发数量",
   "severity": "fix",
   "polarity": "must",
   "condition": "引用在售产品数量",
   "scope": [
    "body"
   ],
   "scope_note": "本规则只在文章引用「在售产品数量」时适用，要求说明该数字是官网当期在售数量。\n不构成违反的情形：\n- 文章未提及在售产品数量。\n- 提到产品数量时已说明口径（如「官网在售80款」）。\n判为违反需文中出现产品数量但把它写成累计开发数量，或未说明口径导致歧义。",
   "needs_source": false
  },
  {
   "id": "QH-D05",
   "statement": "权益类表述须加限定，写「符合条件的保单客户」",
   "severity": "fix",
   "polarity": "must",
   "condition": "涉及增值权益归属",
   "scope": [
    "body"
   ],
   "scope_note": "本规则只在文章提到保单客户可享有的增值权益时适用，要求加限定语。\n不构成违反的情形：\n- 未提及增值权益、医疗直付、养老社区入住等内容。\n- 已写「符合条件的保单客户」「符合条件的客户」。\n判为违反需出现「客户可对接」「保单客户可享」等未加限定的表述，暗示所有客户均可享受。",
   "needs_source": false
  },
  {
   "id": "QH-D06",
   "statement": "不得把公司理赔数据、医养服务数据归为跨境养老服务",
   "severity": "reject",
   "polarity": "must_not",
   "condition": null,
   "scope": [
    "body"
   ],
   "scope_note": "本规则只禁止一种错误归类：把公司的理赔数据、医养服务数据说成「跨境养老服务」数据。\n不构成违反的情形：\n- 未涉及跨境养老。\n- 单独陈述理赔数据（理赔件数、赔付金额、时效）。\n- 单独陈述医养服务覆盖人次。\n- 正确描述深圳康养社区纳入香港院舍照顾计划这类真实的跨境业务。\n判为违反需把理赔或一般医养服务的数据整体归入跨境养老服务成果。",
   "needs_source": false
  },
  {
   "id": "QH-D07",
   "statement": "官方公众号不止一个，服务功能表述以公众号实际展示为准",
   "severity": "fix",
   "polarity": "must",
   "condition": "提及官方公众号",
   "scope": [
    "body"
   ],
   "scope_note": "本规则只在文章提及官方公众号时适用，要求不把服务功能写死成某一个公众号专属。\n不构成违反的情形：\n- 未提及公众号。\n- 提到公众号时未断言服务功能归属。\n判为违反需明确写「关注XX公众号可办理…」且把功能归给单一公众号。",
   "needs_source": false
  }
 ],
 "skipped": [
  {
   "id": "QH-P07",
   "why": "需对照知识库原文",
   "statement": "素材未提供或官网未披露的内容不得编造"
  },
  {
   "id": "QH-F02",
   "why": "人工流程项",
   "statement": "「大部分产品红利实现率超过100%」须先经官方或第三方核实后方可使用"
  },
  {
   "id": "QH-F05",
   "why": "人工流程项",
   "statement": "如需回应，须写明 2022 年免职决议未生效、董监高目前正常履职"
  },
  {
   "id": "QH-I02",
   "why": "may 类不进合格率",
   "statement": "可将本公司表述为「有代表性的机构」或「其中之一」"
  },
  {
   "id": "QH-S01",
   "why": "prefer 类不进合格率",
   "statement": "市场地位非必要不主动输出；确需表述时用「中小型险企」或「中等规模险企」"
  },
  {
   "id": "QH-C01",
   "why": "may 类不进合格率",
   "statement": "保险与医养业务可以同时出现，但须从行业角度分别陈述各自业务逻辑"
  },
  {
   "id": "QH-C03",
   "why": "may 类不进合格率",
   "statement": "可以从行业通用逻辑切入说明业务价值，但不得把行业通用服务写成本公司专属能力"
  },
  {
   "id": "QH-T02",
   "why": "prefer 类不进合格率",
   "statement": "结论前置，首段直接回扣标题主题，不铺垫行业背景"
  },
  {
   "id": "QH-T03",
   "why": "prefer 类不进合格率",
   "statement": "按「股权 → 经营 → 保单」三个维度展开（客户已认可该结构）"
  },
  {
   "id": "QH-T05",
   "why": "prefer 类不进合格率",
   "statement": "已提供素材须充分展开，提高素材覆盖率，不大量留白"
  },
  {
   "id": "QH-D02",
   "why": "prefer 类不进合格率",
   "statement": "数据非必要不用；不主动公开较新年度的经营数据"
  },
  {
   "id": "QH-L01",
   "why": "人工流程项",
   "statement": "稿件须经 编辑室 → 相关领导 → 法务合规 → 消费者权益保护中心 四道审核"
  },
  {
   "id": "QH-L02",
   "why": "人工流程项",
   "statement": "先产出标题与文章架构供甲方确认，确认后再产出正文（单批不超过 5 篇）"
  },
  {
   "id": "QH-L03",
   "why": "人工流程项",
   "statement": "对红利实现率等素材做官方或第三方核实，核不出处的主动上报，不硬写"
  },
  {
   "id": "QH-L04",
   "why": "人工流程项",
   "statement": "必须保留人工把控环节，不依赖机器全自动产出"
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
