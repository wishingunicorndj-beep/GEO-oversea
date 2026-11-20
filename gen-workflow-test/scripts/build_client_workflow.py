#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把客户规则包注入通用生文工作流，生成客户定制版 yml。

设计前提：
  拓扑冻结 —— 只改节点内部 prompt 与一个代码门禁节点，不增删节点、不改连线。
  规则与知识库分离 —— 规则包只提供"该怎么写"，企业事实由知识库服务供给。
  文档结构无关 —— 规则按 category/polarity 注入，不依赖客户文件的组织方式。

用法：
  python3 scripts/build_client_workflow.py clients/前海人寿/rules.yaml
  python3 scripts/build_client_workflow.py clients/<客户>/rules.yaml --dry-run
"""
import argparse
import json
import os
import re
import sys

import yaml

from gate_template import GATE_MODULE
from rule_schema import active_rules

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(BASE)

# 母版查找顺序：
#   1) 环境变量 GEO_TEMPLATE 显式指定
#   2) 项目内 assets/（部署到容器时用这份，随镜像分发）
#   3) 仓库根 workflows/（本地开发，与仓库母版保持同步）
def _find_template():
    env = os.environ.get("GEO_TEMPLATE")
    if env and os.path.exists(env):
        return env
    for cand in (os.path.join(BASE, "assets", "通用生文工作流.yml"),
                 os.path.join(REPO, "workflows", "通用生文工作流.yml")):
        if os.path.exists(cand):
            return cand
    raise SystemExit("找不到母版工作流：请设置 GEO_TEMPLATE，或把 通用生文工作流.yml 放到 assets/ 下")

TEMPLATE = _find_template()

NODE_BY_KEY = {
    "N4": "N4 通用 GEO 画像分析",
    "N6": "N6 通用文章大纲",
    "N7": "N7 通用规则生文",
    "N7b": "N7b 通用内容审核",
}

# 母版节点 ID（拓扑冻结，ID 在各客户版之间一致）
ENT_PARSE_ID = "17769420852870"   # 企业知识库解析
PROD_PARSE_ID = "1776941890551"   # 产品/服务知识库解析
GATE_NODE_ID = "1777100000001"    # N8-pre 通用文章清洗

CATEGORY_LABEL = {
    "identity": "实体称谓",
    "fact": "事实表述口径",
    "prohibition": "禁止事项",
    "stance": "自我定位",
    "scope": "业务边界",
    "voice": "口吻与体裁",
    "structure": "文章结构",
    "citation": "数据与引用",
    "delivery": "交付流程",
}

# 极性 -> 注入时的措辞前缀
POLARITY_PREFIX = {
    "must": "必须",
    "must_not": "不得",
    "may": "可以",
    "prefer": "建议",
}


def load_rules(path):
    with open(path, encoding="utf-8") as f:
        rules = yaml.safe_load(f)
    for key in ("meta", "rules", "injection_map"):
        if key not in rules:
            sys.exit(f"规则包缺少必需字段：{key}")
    # 软删除的规则留在 yaml 里供审计，但不参与注入
    rules["rules"] = active_rules(rules)
    return rules


def _is_active(rule):
    """状态为待确认/待核实的规则照样注入，但标注出来。"""
    return True


def _render_rule(rule):
    """把一条规则渲染成一行（含可选的替代写法）。"""
    prefix = POLARITY_PREFIX.get(rule.get("polarity"), "")
    stmt = rule.get("statement") or ""
    cond = rule.get("condition")
    sev = rule.get("severity")

    # statement 已以极性词开头时不再重复前缀
    if stmt.startswith(prefix):
        stmt = stmt[len(prefix):].lstrip("：:，,")

    tag = {"reject": "拒稿线", "fix": "必须改", "advise": ""}.get(sev, "")
    head = f"- {prefix}：{stmt}"
    if cond:
        head = f"- {prefix}（{cond}）：{stmt}"
    if tag:
        head += f"〔{tag}〕"
    alt = rule.get("alternative")
    if alt:
        head += f"\n  改法：{alt}"
    if rule.get("status") == "needs_confirmation":
        head += "\n  注：此条适用范围待客户确认，暂按回避处理"
    if rule.get("status") == "blocked_pending_verification":
        head += "\n  注：须先完成核实方可使用"
    for ex in rule.get("examples") or []:
        head += f"\n  错误写法：{ex.get('wrong')}\n  正确写法：{ex.get('right')}"
    return head


def build_block(categories, rules, client_name):
    """按类别组织规则块。must/must_not 在前，may/prefer 在后。

    delivery 类（人工审核流程等）不注入 prompt —— 它们约束的是交付流程，
    不是文章写法，写进 prompt 只会干扰模型。
    """
    cats = [c for c in categories if c != "delivery"]
    picked = [r for r in rules["rules"] if r.get("category") in cats]
    if not picked:
        return ""

    order = {"must": 0, "must_not": 1, "may": 2, "prefer": 3}
    sections = []
    for cat in categories:
        items = [r for r in picked if r.get("category") == cat]
        if not items:
            continue
        items.sort(key=lambda r: order.get(r.get("polarity"), 9))
        lines = [_render_rule(r) for r in items]
        sections.append(f"### {CATEGORY_LABEL.get(cat, cat)}\n" + "\n".join(lines))

    header = (
        f"\n\n# {client_name} 客户写作规范（优先级高于知识库与一般写作偏好）\n"
        "以下为客户书面确认的规则。与知识库冲突时以本节为准；"
        "本节只规定怎么写，知识库未提供的事实不得据此补写。\n\n"
    )
    return header + "\n\n".join(sections)


def inject_prompt(text, block):
    """把注入块插到 system prompt 的 `# 输出` 之前；没有则追加。"""
    if not block:
        return text
    m = re.search(r"^#\s*输出", text, re.M)
    if m:
        return text[: m.start()].rstrip() + block + "\n\n" + text[m.start():]
    return text.rstrip() + block


def build_detect_payload(rules):
    """抽出代码门禁需要的确定性规则。

    product_names 支持两种写法：纯字符串，或 {name, aliases} 字典。
    aliases 用于兜住简称与素材里的另一种写法，只有整个系列都下架时才可填系列名。

    除「拦」以外还支持三类「改」：
      replace      旧表述 → 新表述的自动替换（客户改名、课程更名）
      brand_combo  品牌名紧跟学科名的组合写法，单独成规则因为要两侧都点名
      required     客户要求每篇尽量出现的要素（官网、统一电话），缺失只告警不阻断
    联系方式白名单走规则包顶层的 gate.contact_whitelist，因为它是对母版清洗
    默认行为的例外，不属于任何一类写作规则。
    """
    title_terms, body_terms, title_regex, body_regex = [], [], [], []
    product_names = []
    replacements = []
    brand_combo = {}
    required = []
    flags = set()
    for r in rules["rules"]:
        det = r.get("detect") or {}
        if not det:
            continue
        # enforcement=llm 但带 detect 的规则（广告法极限词这类），语义判断仍归模型，
        # 正则只负责把可疑句挑出来报给业务；因此进 warn，不升 hard。
        is_code = r.get("enforcement") == "code"
        scope = r.get("scope") or ["title", "body"]
        dtype = det.get("type")
        values = det.get("values") or []
        if dtype == "terms":
            entry = {"id": r["id"], "terms": values,
                     "action": r.get("action") or "命中客户禁用词"}
            if "title" in scope:
                title_terms.append(entry)
            if "body" in scope:
                body_terms.append(entry)
        elif dtype == "regex":
            entry = {"id": r["id"], "patterns": values,
                     "level": "hard" if is_code else (r.get("level") or "warn"),
                     "action": r.get("action") or "命中客户禁用模式"}
            if "title" in scope:
                title_regex.append(entry)
            if "body" in scope:
                body_regex.append(entry)
        elif dtype == "product_names":
            for v in values:
                if isinstance(v, dict):
                    product_names.append({
                        "name": v.get("name", ""),
                        "aliases": v.get("aliases") or [],
                    })
                else:
                    product_names.append({"name": v, "aliases": []})
        elif dtype == "replace":
            for v in values:
                if isinstance(v, dict) and v.get("from") and v.get("to"):
                    replacements.append({"id": r["id"],
                                         "from": v["from"], "to": v["to"]})
        elif dtype == "brand_combo":
            brand_combo = {
                "id": r["id"],
                "brands": det.get("brands") or [],
                "subjects": det.get("subjects") or [],
            }
        elif dtype == "required":
            required.append({
                "id": r["id"],
                "label": r.get("label") or r["id"],
                "patterns": values,
                "level": r.get("level") or "warn",
                "action": r.get("action") or "缺客户要求出现的要素",
            })
        elif dtype in ("faq_numbering", "place_enumeration"):
            flags.add(dtype)

    gate_cfg = rules.get("gate") or {}
    return {
        "title_terms": title_terms,
        "body_terms": body_terms,
        "title_regex": title_regex,
        "body_regex": body_regex,
        "product_names": product_names,
        "replacements": replacements,
        "brand_combo": brand_combo,
        "required": required,
        "contact_whitelist": gate_cfg.get("contact_whitelist") or [],
        "check_faq_numbering": "faq_numbering" in flags,
        "check_place_enumeration": "place_enumeration" in flags,
    }


def gate_code(rules, base_code):
    """在通用版清洗逻辑之上追加客户规则门禁（保留全部原有清洗函数）。

    门禁主体在 gate_template.py 里维护；这里只负责把规则包抽出的 payload
    填进去，并给母版 `_clean_text` 里的联系方式清洗打上白名单补丁。
    """
    payload = build_detect_payload(rules)
    data = json.dumps(payload, ensure_ascii=False, indent=1)
    head = base_code.split("def main(")[0].rstrip()

    # 母版无条件删除「联系电话：…」，客户要求每篇带统一电话时必须放行。
    # 不在母版上改，只在这个客户版里把那一行换掉。
    if payload["contact_whitelist"]:
        old = ("    text = re.sub(r'(?i)(?:联系电话|联系方式|咨询电话|扫码添加)"
               "[：:：]?\\s*[^<。！？\\n]{0,80}', '', text)")
        new = ("    # 联系方式清洗改为走白名单，保留客户要求必带的统一电话"
               "\n    text = _strip_contacts(text)")
        if old not in head:
            sys.exit("母版 N8-pre 的联系方式清洗行已变化，白名单补丁无法定位；"
                     "请先核对 workflows/通用生文工作流.yml 的 _clean_text")
        head = head.replace(old, new)
        # 白名单函数定义在 GATE 之后，但 _clean_text 在运行时才调用它，顺序无碍
        head = head.replace("def _clean_text(value):",
                            "def _clean_text(value):  # noqa: E302")

    return head + "\n" + GATE_MODULE.replace("__GATE_JSON__", data) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rules", help="客户规则包 yaml 路径")
    ap.add_argument("--template", default=TEMPLATE)
    ap.add_argument("--out", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rules = load_rules(args.rules)
    meta = rules["meta"]
    client = meta.get("client_name") or meta["client_id"]
    short = meta.get("client_short") or client

    with open(args.template, encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    doc["app"]["name"] = f"{short}生文工作流"
    doc["app"]["description"] = (
        f"{short} 定制生文工作流 · 规则包 v{meta.get('version', '')}"
        f"（{len(rules['rules'])} 条规则）"
    )

    inj = rules["injection_map"]
    stats = {}

    for node in doc["workflow"]["graph"]["nodes"]:
        dt = node.get("data") or {}
        title = dt.get("title")

        target = None
        for key, tname in NODE_BY_KEY.items():
            if title == tname:
                target = key
                break

        if target and inj.get(target):
            block = build_block(inj[target], rules, short)
            if block:
                for msg in dt.get("prompt_template") or []:
                    if msg.get("role") == "system":
                        before = len(msg["text"])
                        msg["text"] = inject_prompt(msg["text"], block)
                        stats[target] = (before, len(msg["text"]), len(inj[target]))

        if title == "N8-pre 通用文章清洗":
            dt["code"] = gate_code(rules, dt.get("code") or "")
            outs = dt.get("outputs") or {}
            outs["gate_report"] = {"children": None, "type": "array[object]"}
            dt["outputs"] = outs
            dt["desc"] = "清洗 + 客户规则代码门禁"
            # 地名白名单需要知识库原文，接上两个解析节点的 content
            vars_ = dt.get("variables") or []
            have = {v.get("variable") for v in vars_}
            for var, node_id in (("ent_body", ENT_PARSE_ID), ("prod_body", PROD_PARSE_ID)):
                if var in have:
                    continue
                vars_.append({
                    "value_selector": [node_id, "content"],
                    "variable": var,
                })
            dt["variables"] = vars_

    # 门禁报告原本无处输出，接进结束节点，业务侧才能看到本篇命中了哪些拒稿线
    for node in doc["workflow"]["graph"]["nodes"]:
        dt = node.get("data") or {}
        if dt.get("type") != "end":
            continue
        outs = dt.get("outputs") or []
        if not any(o.get("variable") == "gate_report" for o in outs):
            outs.append({
                "value_selector": [GATE_NODE_ID, "gate_report"],
                "variable": "gate_report",
            })
        dt["outputs"] = outs

    out_path = args.out or os.path.join(BASE, "output", f"{short}生文.yml")

    if args.dry_run:
        print(f"dry-run → {out_path}")
        for k, (a, b, n) in stats.items():
            print(f"  {k}: {n} 个类别, prompt {a} → {b} 字")
        return

    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False, width=4096)
    print(f"已生成: {out_path}")
    for k, (a, b, n) in stats.items():
        print(f"  {k}: {n} 个类别, prompt {a} → {b} 字")


if __name__ == "__main__":
    main()
