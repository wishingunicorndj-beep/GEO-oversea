#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把抽取出的规则初稿（draft JSON）转成正式规则包（rules.yaml）。

职责：
  1. schema 对齐：draft 的 R01 等临时 id 换成带客户前缀的稳定 id。
  2. 补 detect：enforcement=code 的规则，从 statement/evidence 中推导词表或正则。
  3. 补 client_meta / injection_map / priority 等生成器需要的段。
  4. 保留 conflicts 与 not_rules —— 业务审阅时要知道「哪些被刻意没抽成规则」。
  5. 校验：category/polarity/severity/enforcement 合法性、code 规则必须有 detect、
     delivery 类不参与注入与判定（由下游脚本按 category 过滤）。

用法：
  python3 scripts/draft_to_rules.py /tmp/qh_rules_draft.json --slug qianhai_life --out clients/前海人寿/rules_extracted.yaml
  python3 scripts/draft_to_rules.py draft.json --slug ldx --out clients/利多星/rules.yaml --dry-run
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

CATEGORIES = {"identity", "fact", "prohibition", "stance", "scope", "voice", "structure", "citation", "delivery"}
POLARITIES = {"must", "must_not", "may", "prefer"}
SEVERITIES = {"reject", "fix", "advise"}
ENFORCEMENTS = {"code", "llm", "human"}

# 注入映射：category -> 节点。delivery 刻意不在其中（不注入、不判定）。
INJECTION_MAP = {
    "N4": ["identity", "fact", "stance"],
    "N6": ["identity", "scope", "structure", "voice"],
    "N7": ["fact", "citation", "scope", "structure", "voice"],
    "N7b": ["prohibition", "identity", "fact", "citation", "structure", "voice"],
    "code_gate": ["prohibition", "identity"],
}

# 引号包裹的候选词表：中文引号、英文引号、书名号
QUOTED = re.compile(r"[「『“\"]([^」』”\"]{1,20})[」』”\"]")


def slug_prefix(slug):
    return re.sub(r"[^A-Za-z]", "", slug).upper()[:6] or "CL"


def infer_detect(rule):
    """为 code 类规则推导可命中的词表或正则。

    只做保守推导：能从引号里取到「禁止出现的对象」就用词表；识别到电话/URL 等模式用正则。
    推不出来时返回 None，由调用方降级为 llm 并记录。

    关键约束：只能取「被禁止的写法」，不能取「替代写法」。
    例：「标题不得使用『宝能集团』，应以『股东』代指」——『股东』是正确的替代写法，
    若一并放进词表会造成整批误报。
    """
    statement = rule.get("statement") or ""
    evidence = rule.get("evidence") or ""
    scope_note = rule.get("scope_note") or ""
    text = " ".join([statement, scope_note, evidence])

    # 1) 电话、URL、引流类
    if re.search(r"电话|热线|联系方式|客服号", text) and re.search(r"\d{3,}", text):
        return {
            "type": "regex",
            "values": [r"\d{3,4}-\d{3,4}-\d{3,4}", r"\d{7,12}", r"扫码", r"加微信"],
        }

    # 2) 产品名：整句列出多款产品时按顿号/以及/和 切分
    if re.search(r"不得(?:提及|写入|出现|使用)", statement) and re.search(r"保险|产品|款", statement):
        body = re.sub(r"^.*?不得(?:提及|写入|出现|使用)\s*", "", statement)
        body = re.sub(r"[。；]$", "", body).strip()
        parts = [p.strip() for p in re.split(r"[、，,]|以及|和(?=[^)]*保险)|及(?=[^)]*保险)|及(?=[^)]*[）)]?[）)])", body) if p.strip()]
        parts = [p for p in parts if 4 <= len(p) <= 60]
        # 去掉「且本次明确要求删除」「等产品内容不得保留」这类描述性残句
        clean = []
        for p in parts:
            p = re.sub(r"^(?:且|并|以及)?\s*(?:本次|此次)?\s*(?:明确)?\s*(?:要求)?\s*(?:删除|禁提|不再提及)?\s*(?:的)?\s*", "", p)
            p = re.sub(r"(?:内容|产品内容)?\s*(?:不得保留|不得提及|不再出现|均不得提及).*$", "", p)
            # 去掉「三款指定产品」「等产品」这类数量/泛指尾缀
            p = re.sub(r"\s*(?:等)?(?:[一二三四五六七八九十两\d]+款)?(?:指定|相关|该类)?(?:产品|款)?\s*$", "", p)
            p = p.strip(' "\'“”「」的')
            if not p or len(p) < 4:
                continue
            # 泛称不是产品名：「已下架产品」「相关产品」等
            if re.match(r"^(?:已下架|已停售|相关|该类|上述|本次|全部|所有)", p):
                continue
            # 含「且/并/要求/删除/保留/本次」等词的多半是描述而不是产品名
            if re.search(r"(?:且|并且|要求|删除|保留|本次|不得|应当)", p):
                continue
            clean.append(p)
        if clean:
            return {"type": "product_names", "values": clean}
        if len(parts) >= 1:
            return {"type": "product_names", "values": parts}

    # 3) 从 statement 中取「不得使用 X」里的 X；排除「应以 Y 代指」这类替代写法
    forbidden_part = statement
    # 截断到「应/改用/改为/代指」之前，后面是替代写法不是禁用对象
    m = re.split(r"[，,]?\s*(?:应(?:以|当|使用)|改用|改为|用[^，。]{0,8}代指|替换为)", statement)
    if len(m) > 1:
        forbidden_part = m[0]

    terms = []
    for mm in QUOTED.finditer(forbidden_part):
        v = mm.group(1).strip()
        if 1 <= len(v) <= 12 and not re.search(r"[，。；：、]", v):
            terms.append(v)

    # statement 没取到时，退到 evidence 的「不得/禁止」上下文里取
    if not terms:
        m2 = re.search(r"(?:不得|禁止|严禁)([^。；]{0,80})", evidence)
        src = m2.group(1) if m2 else ""
        for mm in QUOTED.finditer(src):
            v = mm.group(1).strip()
            if 1 <= len(v) <= 8 and not re.search(r"[，。；：、]", v):
                terms.append(v)

    seen, uniq = set(), []
    for t in terms:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    if uniq:
        return {"type": "terms", "values": uniq}
    return None


def convert(draft, slug, client_name=None, client_short=None):
    meta = draft.get("_meta") or {}
    client = draft.get("client") or {}
    prefix = slug_prefix(slug)

    rules_out, warnings = [], []
    for idx, r in enumerate(draft.get("rules") or [], 1):
        rid = f"{prefix}-{idx:02d}"
        cat = (r.get("category") or "").strip()
        pol = (r.get("polarity") or "").strip()
        sev = (r.get("severity") or "").strip()
        enf = (r.get("enforcement") or "").strip()

        for name, val, allowed in (
            ("category", cat, CATEGORIES),
            ("polarity", pol, POLARITIES),
            ("severity", sev, SEVERITIES),
            ("enforcement", enf, ENFORCEMENTS),
        ):
            if val not in allowed:
                warnings.append(f"{rid}: {name}={val!r} 非法，已按默认值修正")
        cat = cat if cat in CATEGORIES else "fact"
        pol = pol if pol in POLARITIES else "must"
        sev = sev if sev in SEVERITIES else "fix"
        enf = enf if enf in ENFORCEMENTS else "llm"

        item = {
            "id": rid,
            "category": cat,
            "polarity": pol,
            "severity": sev,
            "scope": r.get("scope") or ["title", "body"],
            "statement": (r.get("statement") or "").strip().rstrip("。"),
        }
        if r.get("condition"):
            item["condition"] = r["condition"].strip()
        if r.get("scope_note"):
            item["scope_note"] = r["scope_note"].strip()
        if r.get("alternative"):
            item["alternative"] = r["alternative"].strip()

        # 确定性推导的硬前提：只有「禁止类」规则才能推出禁用词表。
        # must / may / prefer 类规则引号里的是「正确写法」，放进禁用词表会反向误判。
        #   例：must「应采用『中小型险企』」——『中小型险企』是正确写法，不是禁用词。
        can_mine = (pol == "must_not")
        det = infer_detect(r) if (enf != "human" and can_mine) else None
        if det:
            if enf != "code":
                warnings.append(f"{rid}: 推导到可命中的禁用词表，{enf} 升级为 code")
            enf = "code"
            item["detect"] = det
        elif enf == "code":
            enf = "llm"
            reason = "非禁止类规则不推禁用词" if not can_mine else "无法推导 detect"
            warnings.append(f"{rid}: {reason}，已从 code 降级为 llm")
        item["enforcement"] = enf

        if r.get("evidence"):
            item["evidence"] = r["evidence"].strip()
        if r.get("source_file"):
            item["source_file"] = r["source_file"]
        if r.get("examples"):
            ex = [e for e in r["examples"] if isinstance(e, dict) and (e.get("wrong") or e.get("right"))]
            if ex:
                item["examples"] = ex
        rules_out.append(item)

    from collections import Counter
    cat_n = Counter(x["category"] for x in rules_out)
    pol_n = Counter(x["polarity"] for x in rules_out)
    enf_n = Counter(x["enforcement"] for x in rules_out)

    doc = {
        "meta": {
            "client_id": slug,
            "client_name": client_name or client.get("name") or slug,
            "client_short": (client_short or client.get("short") or client_name
                             or client.get("name") or slug),
            "industry": client.get("industry") or "",
            "version": "0.1.0-draft",
            "compiled_at": "",
            "topology": "generic-18",
            "extraction": {
                "model": meta.get("model"),
                "prompt_chars": meta.get("prompt_chars"),
                "elapsed_s": meta.get("elapsed_s"),
                "source_files": meta.get("source_files") or client.get("source_files") or [],
            },
            "note": "由脚本从客户资料自动抽取，需人工复核后转正（version 去掉 -draft）。",
        },
        "priority": [
            "客户规则 > 知识库原文 > 模型常识",
            "客户资料之间冲突时见 conflicts，未裁决前不得擅自择一",
        ],
        "rules": rules_out,
        "injection_map": INJECTION_MAP,
        "conflicts": draft.get("conflicts") or [],
        "not_rules": draft.get("not_rules") or [],
        "stats": {
            "total": len(rules_out),
            "by_category": dict(cat_n),
            "by_polarity": dict(pol_n),
            "by_enforcement": dict(enf_n),
            "delivery_excluded": cat_n.get("delivery", 0),
        },
    }
    return doc, warnings


def validate(doc):
    errs = []
    ids = set()
    for r in doc["rules"]:
        if r["id"] in ids:
            errs.append(f"重复 id {r['id']}")
        ids.add(r["id"])
        if not r.get("statement"):
            errs.append(f"{r['id']} 缺 statement")
        if not r.get("evidence"):
            errs.append(f"{r['id']} 缺 evidence")
        if r["enforcement"] == "code" and not r.get("detect"):
            errs.append(f"{r['id']} code 规则缺 detect")
        if r["category"] == "delivery" and "detect" in r:
            errs.append(f"{r['id']} delivery 类不应带 detect")
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("draft")
    ap.add_argument("--slug", required=True, help="客户标识，用于生成规则 id 前缀")
    ap.add_argument("--client-name", default=None)
    ap.add_argument("--client-short", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))
    doc, warnings = convert(draft, args.slug, args.client_name, args.client_short)

    errs = validate(doc)
    s = doc["stats"]

    print(f"规则 {s['total']} 条 → {args.out}")
    print(f"  类别: {s['by_category']}")
    print(f"  极性: {s['by_polarity']}")
    print(f"  执行: {s['by_enforcement']}")
    print(f"  delivery 类（不注入、不判定）: {s['delivery_excluded']} 条")
    if warnings:
        print(f"\n修正 {len(warnings)} 处:")
        for w in warnings:
            print("  -", w)
    if errs:
        print(f"\n校验失败 {len(errs)} 项:")
        for e in errs:
            print("  -", e)
        sys.exit(1)
    print("\n校验通过")

    if args.dry_run:
        print("dry-run，未写文件")
        return

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# 客户规则包（由 extract_rules.py + draft_to_rules.py 自动生成）\n"
        "# 状态: draft —— 需人工复核 conflicts 与 not_rules 后转正\n"
        f"# 来源: {', '.join((doc['meta']['extraction'].get('source_files') or []))}\n\n"
    )
    out.write_text(header + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=4000),
                   encoding="utf-8")
    print(f"已写入 {out}")


if __name__ == "__main__":
    main()
