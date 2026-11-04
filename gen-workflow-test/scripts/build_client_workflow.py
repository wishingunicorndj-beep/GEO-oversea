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

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 母版来自仓库根目录的 workflows/，本项目只做定制生成，不改母版
REPO = os.path.dirname(BASE)
TEMPLATE = os.path.join(REPO, "workflows", "通用生文工作流.yml")

NODE_BY_KEY = {
    "N4": "N4 通用 GEO 画像分析",
    "N6": "N6 通用文章大纲",
    "N7": "N7 通用规则生文",
    "N7b": "N7b 通用内容审核",
}

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
    """抽出代码门禁需要的确定性规则。支持 terms / regex / product_names。"""
    title_terms, body_terms, title_regex, body_regex, product_names = [], [], [], [], []
    for r in rules["rules"]:
        if r.get("enforcement") != "code":
            continue
        det = r.get("detect") or {}
        scope = r.get("scope") or ["title", "body"]
        dtype = det.get("type")
        values = det.get("values") or []
        if dtype == "terms":
            entry = {"id": r["id"], "terms": values}
            if "title" in scope:
                title_terms.append(entry)
            if "body" in scope:
                body_terms.append(entry)
        elif dtype == "regex":
            entry = {"id": r["id"], "patterns": values, "label": r.get("statement", "")}
            if "title" in scope:
                title_regex.append(entry)
            if "body" in scope:
                body_regex.append(entry)
        elif dtype == "product_names":
            product_names.extend(values)
    return {
        "title_terms": title_terms,
        "body_terms": body_terms,
        "title_regex": title_regex,
        "body_regex": body_regex,
        "product_names": product_names,
    }


def gate_code(rules, base_code):
    """在通用版清洗逻辑之上追加客户规则门禁（保留全部原有清洗函数）。"""
    payload = build_detect_payload(rules)
    data = json.dumps(payload, ensure_ascii=False, indent=1)
    head = base_code.split("def main(")[0].rstrip()

    return head + f'''

# ---------------------------------------------------------------------------
# 客户规则代码门禁（由 build_client_workflow.py 从规则包生成，勿手改）
# 只做可确定性检出的规则；语义类规则由 LLM 节点执行。
# ---------------------------------------------------------------------------
GATE = json.loads(r"""{data}""")


def _strip_tags(html):
    return re.sub(r'<[^>]+>', '', str(html or ''))


def _hits(text, terms):
    return [t for t in terms if t and t in text]


def _regex_hits(text, patterns):
    hits = []
    for p in patterns:
        try:
            m = re.search(p, text)
        except re.error:
            continue
        if m:
            hits.append(m.group(0)[:30])
    return hits


def _apply_gate(art):
    """在清洗后的文章上执行确定性检查。只标注与定向删除，不重写语义。"""
    issues = []
    title = str(art.get('title') or '')
    content = str(art.get('content') or '')
    body = _strip_tags(content)

    for rule in GATE.get('title_terms', []):
        hit = _hits(title, rule['terms'])
        if hit:
            issues.append({{'id': rule['id'], 'level': 'hard', 'field': 'title',
                           'hits': hit, 'action': '标题命中客户禁用词'}})

    for rule in GATE.get('body_terms', []):
        hit = _hits(body, rule['terms'])
        if hit:
            issues.append({{'id': rule['id'], 'level': 'hard', 'field': 'body',
                           'hits': hit, 'action': '正文命中客户禁用词'}})

    for rule in GATE.get('title_regex', []):
        hit = _regex_hits(title, rule['patterns'])
        if hit:
            issues.append({{'id': rule['id'], 'level': 'hard', 'field': 'title',
                           'hits': hit, 'action': '标题命中客户禁用模式'}})

    for rule in GATE.get('body_regex', []):
        hit = _regex_hits(body, rule['patterns'])
        if hit:
            issues.append({{'id': rule['id'], 'level': 'hard', 'field': 'body',
                           'hits': hit, 'action': '正文命中客户禁用模式'}})

    for name in GATE.get('product_names', []):
        if not name or name not in body:
            continue
        issues.append({{'id': 'PRODUCT', 'level': 'hard', 'field': 'body',
                       'hits': [name], 'action': '含客户禁提产品，已删除相关句子'}})
        parts = re.split(r'(?<=[。！？\\n])', content)
        content = ''.join(p for p in parts if name not in _strip_tags(p))

    out = dict(art)
    out['content'] = content
    if issues:
        summary = '；'.join("%s:%s" % (i['id'], '/'.join(i['hits'])) for i in issues)
        out['self_review'] = (str(out.get('self_review') or '') + '\\n[门禁] ' + summary).strip()
    return out, issues


def main(articles=None):
    if not isinstance(articles, list):
        return {{'cleaned_articles': [], 'gate_report': []}}
    cleaned = []
    report = []
    for raw in articles:
        art = _parse(raw)
        if not art: continue
        title = _clean_text(art.get('title') or art.get('headline'))
        description = _clean_text(art.get('description') or art.get('meta_description'))
        content = _clean_text(art.get('content') or art.get('body'))
        tags = _clean_tags(art.get('tags'))
        review = _clean_text(art.get('self_review') or art.get('review'))
        if not title and content:
            first = re.sub(r'<[^>]+>', '', content).strip().split('\\n')[0]
            title = first[:40]
        if not content: continue
        item = {{'title': title, 'description': description, 'content': content,
                 'tags': tags, 'self_review': review}}
        item, issues = _apply_gate(item)
        cleaned.append(item)
        if issues:
            report.append({{'title': item.get('title', ''), 'issues': issues}})
    return {{'cleaned_articles': cleaned, 'gate_report': report}}
'''


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
