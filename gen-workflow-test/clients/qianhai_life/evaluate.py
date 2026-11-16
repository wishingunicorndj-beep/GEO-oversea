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
   "id": "QIANHA-01",
   "statement": "标题不得直接使用“宝能集团”，应以“股东”代指",
   "severity": "fix",
   "polarity": "must_not",
   "detect": {
    "type": "terms",
    "values": [
     "宝能集团"
    ]
   },
   "scope": [
    "title"
   ]
  },
  {
   "id": "QIANHA-03",
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
   "id": "QIANHA-46",
   "statement": "不得提及客户更新点名的尊享安泰2025 C、D版及聚元宝2025 C款分红型两全保险",
   "severity": "fix",
   "polarity": "must_not",
   "detect": {
    "type": "product_names",
    "values": [
     "客户更新点名的尊享安泰2025 C",
     "聚元宝2025 C款分红型两全保险"
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
   "id": "QIANHA-06",
   "statement": "标题与正文必须一致，正文必须实质展开标题所问主题",
   "severity": "reject",
   "polarity": "must",
   "condition": null,
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "严重脱节、文不对题属于拒稿；不是要求正文只能包含标题原词，相关背景可以服务于主题。",
   "needs_source": false
  },
  {
   "id": "QIANHA-07",
   "statement": "稿件不得存在大逻辑错误",
   "severity": "reject",
   "polarity": "must_not",
   "condition": null,
   "scope": [
    "body"
   ],
   "scope_note": "大逻辑错误直接拒稿；小细节问题按修改反馈流程处理，不一概归为拒稿。",
   "needs_source": false
  },
  {
   "id": "QIANHA-09",
   "statement": "不得将保险理赔与医养资源强行关联或作因果嫁接",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "涉及理赔与医养资源时",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "禁止以医养资源证明理赔能力、以理赔时效满足养老需求等牵强关联，不否定经客户确认的业务并列许可。",
   "needs_source": false
  },
  {
   "id": "QIANHA-10",
   "statement": "不得把公司整体理赔数据或整体医养服务数据归为跨境养老服务数据",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "介绍跨境养老服务时",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "限制数据所属业务及人群的错误归类，不禁止使用经核实、确属跨境养老的资料。",
   "needs_source": false
  },
  {
   "id": "QIANHA-11",
   "statement": "不得将医养业务称为公司核心业务",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "介绍公司核心业务时",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "限制“核心业务”的归属，不禁止介绍医养布局或经核实的保险与医养协同模式。",
   "needs_source": false
  },
  {
   "id": "QIANHA-12",
   "statement": "必须注明权益适用于“符合条件的保单客户”，不得泛化为所有客户均可享有",
   "severity": "fix",
   "polarity": "must",
   "condition": "介绍保单客户对接医疗、养老增值权益时",
   "scope": [
    "body"
   ],
   "scope_note": "限制客户资格与权益适用范围，不要求编造具体资格门槛。",
   "needs_source": false
  },
  {
   "id": "QIANHA-13",
   "statement": "不得使用“主流”“头部”“明星”及其他拔高市场地位的表述",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "描述前海人寿市场地位时",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "限制对前海人寿的市场定位，不等于禁止所有包含“头部”等字词的无关语境。",
   "needs_source": false
  },
  {
   "id": "QIANHA-14",
   "statement": "规模定位采用“中小型险企”或“中等规模险企”",
   "severity": "fix",
   "polarity": "must",
   "condition": "确有必要输出公司规模定位时",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "仅约束必要的规模定位，不要求文章主动增加规模标签。",
   "needs_source": false
  },
  {
   "id": "QIANHA-17",
   "statement": "不得与其他保险公司横向对比、进行同业信息盘点或拉踩同业",
   "severity": "fix",
   "polarity": "must_not",
   "condition": null,
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "包括仅突出前海人寿优势而对其他公司只列基础信息的隐性拉踩；竞品名单本身不是获准比较的依据。",
   "needs_source": false
  },
  {
   "id": "QIANHA-18",
   "statement": "理赔内容限定在公司提供的理赔数据、科技赋能、特色理赔服务和真实案例内",
   "severity": "fix",
   "polarity": "must",
   "condition": "理赔业务稿件",
   "scope": [
    "body"
   ],
   "scope_note": "限制理赔内容的素材与能力边界，不要求每篇同时包含全部四类。",
   "needs_source": false
  },
  {
   "id": "QIANHA-19",
   "statement": "不得超范围发挥或将行业通用服务写成公司专属能力",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "理赔业务表述",
   "scope": [
    "body"
   ],
   "scope_note": "禁止无依据的专属性归属，不禁止如实说明公司确实提供的通用服务。",
   "needs_source": false
  },
  {
   "id": "QIANHA-20",
   "statement": "不得使用“高分红”等夸大分红水平的表述",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "分红险稿件",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "限制夸大性宣传，不禁止依据已核实材料客观介绍分红表现。",
   "needs_source": false
  },
  {
   "id": "QIANHA-21",
   "statement": "必须明确区分“演示利率”与“红利实现率”，不得混为一谈",
   "severity": "fix",
   "polarity": "must",
   "condition": "谈及分红险演示利率或红利实现率时",
   "scope": [
    "body"
   ],
   "scope_note": "约束概念与指标关系，不要求无关稿件强行介绍这两个指标。",
   "needs_source": false
  },
  {
   "id": "QIANHA-24",
   "statement": "须从法律层面区分股东与保险公司，说明法人独立、不承担股东债务及保险保障基金机制",
   "severity": "fix",
   "polarity": "must",
   "condition": "股东债务危机类澄清稿件",
   "scope": [
    "body"
   ],
   "scope_note": "约束澄清论证结构，不据此扩展为任意情形均能无条件全额兑付；纪要另有“绝对安全”结论，须单独处理。",
   "needs_source": false
  },
  {
   "id": "QIANHA-26",
   "statement": "须说明2022年免职决议未生效及董监高目前正常履职，并按更新材料核对",
   "severity": "fix",
   "polarity": "must",
   "condition": "针对管理层空缺、2022年免职事件作澄清时",
   "scope": [
    "body"
   ],
   "scope_note": "属于针对性澄清口径，不要求其他词条主动提及董监高，不授权添加个人评价。",
   "needs_source": false
  },
  {
   "id": "QIANHA-27",
   "statement": "不主动提及董监高；相关词条使用时须严格按更新材料表述",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "词条不涉及董监高时",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "仅约束主动披露及材料时效，不等于在管理层空缺澄清词条中全面禁提；例外范围仍需客户确认。",
   "needs_source": false
  },
  {
   "id": "QIANHA-28",
   "statement": "不得写成正规新闻稿或造成公司官方回应、官方澄清的误解",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "负面舆情澄清类稿件",
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "约束叙述身份及官方背书感，不禁止引用已核实的官方公开信息。",
   "needs_source": false
  },
  {
   "id": "QIANHA-29",
   "statement": "须以第三方视角进行客观分析",
   "severity": "fix",
   "polarity": "must",
   "condition": "负面舆情澄清类稿件",
   "scope": [
    "body"
   ],
   "scope_note": "第三方视角不意味着可虚构专家、媒体或“大V”的真实背书。",
   "needs_source": false
  },
  {
   "id": "QIANHA-31",
   "statement": "不得编造客户素材未提供的公司制度、服务、活动或合规结论",
   "severity": "fix",
   "polarity": "must_not",
   "condition": null,
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "尤其包括导师、培训、体检岗位限制及无就业歧视等未经提供的内容；不禁止按流程补充核实后的新资料。",
   "needs_source": false
  },
  {
   "id": "QIANHA-32",
   "statement": "不得声称公司管理规则公开披露、全部以公开正式文件为准或员工可随时查阅公开制度文件",
   "severity": "fix",
   "polarity": "must_not",
   "condition": "员工关系、离职保障或公司管理制度稿件",
   "scope": [
    "body"
   ],
   "scope_note": "限制公开可得性的无依据断言，不禁止介绍已提供的内部制度内容，也不否定通过正式渠道核实。",
   "needs_source": false
  },
  {
   "id": "QIANHA-33",
   "statement": "出处措辞须严谨，不得统称为“企业公开披露内容”",
   "severity": "fix",
   "polarity": "must",
   "condition": "相关员工晋升等信息未见公司官网披露时",
   "scope": [
    "body"
   ],
   "scope_note": "客户允许较宽泛地写“根据公开内容”，但该许可不等于可以没有真实来源。",
   "needs_source": false
  },
  {
   "id": "QIANHA-35",
   "statement": "须分别标明数据年份或统计截止时间，避免造成同一统计期的误解",
   "severity": "fix",
   "polarity": "must",
   "condition": "同句或相邻段落使用不同年份的数据时",
   "scope": [
    "body"
   ],
   "scope_note": "约束跨年份数据拼接，不要求删除所有历史数据。",
   "needs_source": false
  },
  {
   "id": "QIANHA-40",
   "statement": "须明确在售数量对应官网清单的统计时点，并与累计开发产品数量区分",
   "severity": "fix",
   "polarity": "must",
   "condition": "介绍在售产品数量时",
   "scope": [
    "body"
   ],
   "scope_note": "抽取的是在售存量与累计开发量的区分规则，不将80款或420余款固化为写作规则。",
   "needs_source": false
  },
  {
   "id": "QIANHA-41",
   "statement": "监管机构称谓使用“国家金融监督管理总局”，不得在该当前语境沿用“银保监会”",
   "severity": "fix",
   "polarity": "must",
   "condition": "描述当前分红险产品定价监管机构时",
   "scope": [
    "body"
   ],
   "scope_note": "限于客户纠正的当前定价监管表述，不禁止历史事件中准确使用当时机构名称。",
   "needs_source": false
  },
  {
   "id": "QIANHA-42",
   "statement": "使用“按监管要求”表述，不使用“与监管要求高度适配”的说法",
   "severity": "fix",
   "polarity": "must",
   "condition": "说明风险管理体系与监管要求的关系时",
   "scope": [
    "body"
   ],
   "scope_note": "约束监管合规关系的表述，不要求照抄整段公司风险管理事实。",
   "needs_source": false
  },
  {
   "id": "QIANHA-43",
   "statement": "须按各公众号实际展示功能分别说明，不得混用服务号名称及功能",
   "severity": "fix",
   "polarity": "must",
   "condition": "介绍官方微信公众号及其服务功能时",
   "scope": [
    "body"
   ],
   "scope_note": "“前海人寿保险”“前海人寿”均可提供服务，但功能有差异；不是只允许写其中一个。",
   "needs_source": false
  },
  {
   "id": "QIANHA-45",
   "statement": "删除稿件中的“前海智慧优选2026养老年金保险（分红型）”及“前海智慧优选2026A养老年金保险（分红型）”相关内容",
   "severity": "fix",
   "polarity": "must_not",
   "condition": null,
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "针对明确点名的两个分红型产品，不自动扩展到名称相近但未点名的非分红型产品。",
   "needs_source": false
  },
  {
   "id": "QIANHA-47",
   "statement": "不得硬造生词或使用不适合保险行业宣传文章的内部术语组合",
   "severity": "fix",
   "polarity": "must_not",
   "condition": null,
   "scope": [
    "title",
    "body"
   ],
   "scope_note": "例如“内勤服务建设”；不等于禁止在确有必要的内部岗位介绍中准确使用“内勤”。",
   "needs_source": false
  },
  {
   "id": "QIANHA-48",
   "statement": "充分展开已提供且与主题相关的素材，避免只用一段综述或一笔带过",
   "severity": "fix",
   "polarity": "must",
   "condition": null,
   "scope": [
    "body"
   ],
   "scope_note": "要求提高相关素材展开度，不要求全量堆砌所有资料，也不覆盖已禁用或待核实内容。",
   "needs_source": false
  },
  {
   "id": "QIANHA-49",
   "statement": "段落和句子须逻辑连贯，避免模板拼接和与上下文无关的突兀插句",
   "severity": "fix",
   "polarity": "must",
   "condition": null,
   "scope": [
    "body"
   ],
   "scope_note": "尤其包括突然插入保费咨询句、医养布局支撑产品分红等牵强论证；不是禁止合理补充咨询渠道。",
   "needs_source": false
  }
 ],
 "skipped": [
  {
   "id": "QIANHA-02",
   "why": "may 类不进合格率",
   "statement": "正文允许适度提及“宝能集团”"
  },
  {
   "id": "QIANHA-04",
   "why": "人工流程项",
   "statement": "“坚持独立自主经营”被列为受限标题表述，须按适用词条向客户确认后使用"
  },
  {
   "id": "QIANHA-05",
   "why": "prefer 类不进合格率",
   "statement": "标题优先采用服务指引视角，避免事件化、情绪化表达"
  },
  {
   "id": "QIANHA-08",
   "why": "may 类不进合格率",
   "statement": "允许不同业务在同一稿件中出现，但须结合实际行业角度表述"
  },
  {
   "id": "QIANHA-15",
   "why": "prefer 类不进合格率",
   "statement": "不主动输出“中小型险企”或“中等规模险企”等规模定位"
  },
  {
   "id": "QIANHA-16",
   "why": "may 类不进合格率",
   "statement": "允许将前海人寿称为“有代表性的机构”或其中之一"
  },
  {
   "id": "QIANHA-22",
   "why": "may 类不进合格率",
   "statement": "允许公开使用“大部分产品红利实现率超过100%”的表述"
  },
  {
   "id": "QIANHA-23",
   "why": "may 类不进合格率",
   "statement": "允许补充分红险相关数据为动态更新数据的说明"
  },
  {
   "id": "QIANHA-25",
   "why": "人工流程项",
   "statement": "纪要要求以“客户保单绝对安全”作结论，该口径须与条件化法律说明一并提交客户确认"
  },
  {
   "id": "QIANHA-30",
   "why": "prefer 类不进合格率",
   "statement": "优先采用第三方自媒体、大V或论坛帖子式的客观分析体裁"
  },
  {
   "id": "QIANHA-34",
   "why": "may 类不进合格率",
   "statement": "允许使用“根据公开内容”这一出处措辞"
  },
  {
   "id": "QIANHA-36",
   "why": "人工流程项",
   "statement": "不主动公开2025年数据"
  },
  {
   "id": "QIANHA-37",
   "why": "prefer 类不进合格率",
   "statement": "非必要不使用数据"
  },
  {
   "id": "QIANHA-38",
   "why": "prefer 类不进合格率",
   "statement": "尽量避免提及年报、经营数据、保费数据及相关词语"
  },
  {
   "id": "QIANHA-39",
   "why": "人工流程项",
   "statement": "公司偿付能力、风险综合评级须按高敏事项处理，不作未经确认的普通素材输出"
  },
  {
   "id": "QIANHA-44",
   "why": "人工流程项",
   "statement": "不得写入已下架产品"
  },
  {
   "id": "QIANHA-50",
   "why": "prefer 类不进合格率",
   "statement": "优先按股权、经营、保单三个维度展开，并直接切入核心议题"
  },
  {
   "id": "QIANHA-51",
   "why": "人工流程项",
   "statement": "稿件必须加入人工把控和复核，不得完全依赖机器产出"
  },
  {
   "id": "QIANHA-52",
   "why": "人工流程项",
   "statement": "稿件须依次经过编辑室、相关领导、法务合规、消费者权益保护中心审核"
  },
  {
   "id": "QIANHA-53",
   "why": "人工流程项",
   "statement": "产品购买评价类具体用语须额外提交合规消保部门审查"
  },
  {
   "id": "QIANHA-54",
   "why": "人工流程项",
   "statement": "语料须经前海人寿审核同意后方可投放"
  },
  {
   "id": "QIANHA-55",
   "why": "人工流程项",
   "statement": "先提交各词条标题和文章架构供甲方确认，再产出5篇以内人工稿件"
  },
  {
   "id": "QIANHA-56",
   "why": "人工流程项",
   "statement": "对素材进行官方或第三方机构核实，并提前反馈核实结果、无法表述或核不出处的内容"
  },
  {
   "id": "QIANHA-57",
   "why": "人工流程项",
   "statement": "以后续认可的新稿作为量产标准，旧稿作废"
  },
  {
   "id": "QIANHA-58",
   "why": "may 类不进合格率",
   "statement": "允许由甲方直接修改并反馈，不必整篇返工"
  },
  {
   "id": "QIANHA-59",
   "why": "人工流程项",
   "statement": "乙方须主动掌握金融保险术语，并将行业术语、业务逻辑和合规要求整理成文字供模型训练与人工编辑参考"
  },
  {
   "id": "QIANHA-60",
   "why": "人工流程项",
   "statement": "须梳理行业及平台侧禁止或受限表述清单并同步甲方"
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
