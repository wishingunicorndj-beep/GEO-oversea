#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""规则包 schema 单一事实来源：枚举、字段校验、统计重算。

抽取路径（draft_to_rules.py）和人工编辑路径（server.py 保存接口）共用这一份，
避免出现「抽取时校验、手工录入时静默写坏」的两套标准。

校验针对的是「下游会静默失效」的取值，这些不报错但会让规则永远不生效：
  - category 拼错    → 不进 injection_map，工作流 prompt 里没有这条规则
  - scope 写 all     → 评估器 targets 为空，永远判 pass
  - enforcement=code 没有 detect → 评估器永远判 unclear
  - detect.type 不在评估器支持范围 → 永远判 unclear
"""
from collections import Counter

CATEGORIES = ["identity", "fact", "prohibition", "stance", "scope",
              "voice", "structure", "citation", "delivery"]
POLARITIES = ["must", "must_not", "may", "prefer"]
SEVERITIES = ["reject", "fix", "advise"]
ENFORCEMENTS = ["code", "llm", "human"]

# 评估器（build_client_evaluator.check_code_rule）真正能执行的 detect 类型。
# 门禁节点还支持 replace/brand_combo/required/faq_numbering/place_enumeration，
# 但那几种在验收阶段没有对应实现，人工录入时必须拦住。
EVALUATOR_DETECT_TYPES = ["terms", "regex", "product_names"]
ALL_DETECT_TYPES = EVALUATOR_DETECT_TYPES + [
    "replace", "brand_combo", "required", "faq_numbering", "place_enumeration",
]

# 评估器只读 title / body 两个字段（_fields 里 description 与 tags 不参与 code 判定）
VALID_SCOPES = ["title", "body", "tags", "workflow"]

REQUIRED_FIELDS = ["id", "category", "polarity", "severity", "scope", "statement", "enforcement"]

CATEGORY_LABEL = {
    "identity": "实体称谓", "fact": "事实口径", "prohibition": "禁止事项",
    "stance": "自我定位", "scope": "业务边界", "voice": "口吻体裁",
    "structure": "文章结构", "citation": "数据引用", "delivery": "交付流程",
}


def validate_rule(rule, all_ids=None, for_manual_input=True):
    """校验单条规则，返回错误列表（空列表表示通过）。

    all_ids: 其余规则的 id 集合，用于查重（不含本条自身）。
    for_manual_input: True 时按「人工录入」的严格标准校验 ——
      只允许评估器能执行的 detect 类型，避免填了却永远判不出来。
    """
    errs = []
    rid = (rule.get("id") or "").strip()
    label = rid or "(未填 id)"

    for f in REQUIRED_FIELDS:
        if not rule.get(f):
            errs.append(f"{label}：缺少必填字段 {f}")

    if rid and all_ids is not None and rid in all_ids:
        errs.append(f"{label}：规则 id 重复")

    cat = rule.get("category")
    if cat and cat not in CATEGORIES:
        errs.append(f"{label}：category「{cat}」不在 9 类之内"
                    f"（{'/'.join(CATEGORIES)}）。拼错会导致规则不被注入工作流")

    scope = rule.get("scope")
    if scope:
        if not isinstance(scope, list):
            errs.append(f"{label}：scope 必须是数组")
        else:
            bad = [s for s in scope if s not in VALID_SCOPES]
            if bad:
                errs.append(f"{label}：scope 含非法值 {'、'.join(map(str, bad))}"
                            f"（只能取 {'/'.join(VALID_SCOPES)}）")
            # 评估器的代码判定只读 title / body，只写 tags/workflow 会永远判 pass
            if cat != "delivery" and not ({"title", "body"} & set(scope)):
                errs.append(f"{label}：scope 未包含 title 或 body，"
                            f"验收时该规则永远不会命中")

    for name, allowed in (("polarity", POLARITIES), ("severity", SEVERITIES),
                          ("enforcement", ENFORCEMENTS)):
        val = rule.get(name)
        if val and val not in allowed:
            errs.append(f"{label}：{name}「{val}」非法（只能取 {'/'.join(allowed)}）")

    if not (rule.get("statement") or "").strip():
        errs.append(f"{label}：statement（规则本身）不能为空")

    # scope_note 是判定边界，缺了会让模型判定漂移（README 有实测数据）
    if rule.get("enforcement") in ("llm", "code") and not (rule.get("scope_note") or "").strip():
        errs.append(f"{label}：scope_note（判定边界）不能为空。"
                    f"没有边界的规则会让模型判定漂移")

    det = rule.get("detect") or {}
    dtype = det.get("type")
    if rule.get("enforcement") == "code":
        if not det:
            errs.append(f"{label}：enforcement=code 但没有 detect，验收时会永远判「无法判定」")
        elif dtype not in ALL_DETECT_TYPES:
            errs.append(f"{label}：detect.type「{dtype}」不被识别")
        elif for_manual_input and dtype not in EVALUATOR_DETECT_TYPES:
            errs.append(f"{label}：detect.type「{dtype}」门禁支持但验收评估器不支持，"
                        f"人工录入只能用 {'/'.join(EVALUATOR_DETECT_TYPES)}")
        elif not (det.get("values") or []):
            errs.append(f"{label}：detect.values 为空")

    if cat == "delivery" and det:
        errs.append(f"{label}：delivery 类规则约束的是交付流程，不能带 detect")

    return errs


def validate_rule_set(rules, for_manual_input=False):
    """校验整批规则：单条字段 + id 唯一性。返回错误列表。"""
    errs = []
    seen = set()
    for r in rules:
        rid = (r.get("id") or "").strip()
        other = set(seen)
        errs.extend(validate_rule(r, all_ids=other, for_manual_input=for_manual_input))
        if rid:
            seen.add(rid)
    return errs


def next_rule_id(rules, slug):
    """取下一个未占用的规则 id，格式 <前缀>-<两位序号>。

    只增不复用：已删除的编号不再分配给新规则，否则历史批次
    rules_snapshot.yaml 里的 id 会指向一条完全不同的规则。
    """
    import re
    prefix = re.sub(r"[^A-Za-z]", "", slug or "").upper()[:6] or "CL"
    nums = []
    for r in rules:
        m = re.match(r"^%s-(\d+)$" % re.escape(prefix), str(r.get("id") or ""))
        if m:
            nums.append(int(m.group(1)))
    return f"{prefix}-{(max(nums) + 1) if nums else 1:02d}"


def recompute_stats(doc):
    """按当前规则列表重算 stats。保存后必须调用，否则页面统计与实际不符。"""
    rules = doc.get("rules") or []
    cat_n = Counter(r.get("category") for r in rules if r.get("category"))
    pol_n = Counter(r.get("polarity") for r in rules if r.get("polarity"))
    enf_n = Counter(r.get("enforcement") for r in rules if r.get("enforcement"))
    doc["stats"] = {
        "total": len(rules),
        "by_category": dict(cat_n),
        "by_polarity": dict(pol_n),
        "by_enforcement": dict(enf_n),
        "delivery_excluded": cat_n.get("delivery", 0),
    }
    return doc


def active_rules(doc, include_dismissed=False):
    """参与注入与判定的规则。软删除的规则保留在 yaml 里但不生效。"""
    rules = doc.get("rules") or []
    if include_dismissed:
        return rules
    return [r for r in rules if r.get("status") != "dismissed"]


def is_dismissed(conflict):
    """软删除的冲突项：裁决结论为 dismissed，记录保留但不再提示待办。"""
    return (conflict.get("resolution") or {}).get("decision") == "dismissed"


def is_resolved(conflict):
    """是否已形成可执行的裁决结论。

    二选一和删除都算完成；自定义口径必须填了内容才算——
    只存一个 decision=custom 而没有正文，规则那边没有可执行的口径。
    """
    res = conflict.get("resolution") or {}
    decision = res.get("decision")
    if not decision:
        return False
    if decision == "custom":
        return bool(str(res.get("custom_text") or "").strip())
    return True


def is_pending(conflict):
    """仍需人工裁决的冲突项。"""
    return not is_resolved(conflict)


def active_conflicts(doc):
    """未删除的冲突裁决项（含已裁决、未删除的）。"""
    return [c for c in (doc.get("conflicts") or []) if not is_dismissed(c)]


def pending_conflicts(doc):
    """仍需人工裁决的冲突项。转正的门槛看这个。"""
    return [c for c in (doc.get("conflicts") or []) if is_pending(c)]
