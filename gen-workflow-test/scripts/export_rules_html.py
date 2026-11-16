#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把规则包导出成业务可读的 HTML（表格版），用于和客户确认口径。

设计取舍
--------
规则包是给机器读的（YAML），业务看不懂 category / polarity / enforcement。
这份导出要回答业务真正关心的问题：

  1. 客户提了哪些要求？（按「不能做什么 / 必须做什么」分，不是按 category 分）
  2. 每条要求在原文哪里？我能不能核对？
  3. 有什么需要我拍板的？（冲突单独一栏，放在最前）
  4. 哪些没被当成规则？为什么？（避免业务以为漏了）

所以按 polarity 分组而不是按 category 分组 —— 业务脑子里的分类是「禁用」「必须」，
不是「实体称谓 / 事实口径」。

用法：
  python3 scripts/export_rules_html.py clients/<slug>/rules.yaml --out /tmp/rules.html
"""
import argparse
import html
import json
from datetime import datetime
from pathlib import Path

import yaml


def esc(s):
    return html.escape(str(s if s is not None else ''), quote=True)


POLARITY_LABEL = {
    "must_not": ("不能这样写", "禁止"),
    "must": ("必须这样写", "必须"),
    "may": ("客户明确允许", "允许"),
    "prefer": ("建议这样写", "建议"),
}
SEVERITY_LABEL = {
    "reject": ("拒稿线", "red"),
    "fix": ("必须改", "amber"),
    "advise": ("建议", "gray"),
}
ENFORCE_LABEL = {"code": "系统自动检查", "llm": "模型判断", "human": "人工把关"}
CATEGORY_LABEL = {
    "identity": "称谓", "fact": "事实口径", "prohibition": "禁止事项",
    "stance": "市场定位", "scope": "业务边界", "voice": "口吻体裁",
    "structure": "文章结构", "citation": "数据引用", "delivery": "交付流程",
}

CSS = """
:root{--ink:#1a1a1a;--muted:#6b6b6b;--line:#e3e3e3;--bg:#fafafa;
  --red:#c0392b;--amber:#b7791f;--green:#1a7f5a;--blue:#2b6cb0}
*{box-sizing:border-box}
body{margin:0;background:#f4f4f5;color:var(--ink);
  font:14px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
.page{max-width:1080px;margin:0 auto;background:#fff;padding:44px 52px 64px}
h1{font-size:24px;margin:0 0 6px;letter-spacing:-.02em}
.lead{color:var(--muted);font-size:13px;margin:0 0 4px}
.meta{color:#999;font-size:12px;margin-top:10px}

h2{font-size:16px;margin:36px 0 4px;padding-bottom:8px;border-bottom:1px solid var(--line)}
h2 .count{float:right;font-weight:400;font-size:13px;color:var(--muted)}
.hint{color:var(--muted);font-size:12px;margin:8px 0 14px}

table{width:100%;border-collapse:collapse;margin-bottom:8px;font-size:13px}
th{background:var(--bg);text-align:left;padding:9px 12px;font-size:12px;color:#555;
  font-weight:600;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:11px 12px;border-bottom:1px solid #f0f0f0;vertical-align:top}
tr:last-child td{border-bottom:0}
.col-no{width:38px;color:#aaa;font-variant-numeric:tabular-nums}
.col-tag{width:76px;white-space:nowrap}
.col-from{width:150px;color:var(--muted);font-size:12px}

.tag{display:inline-block;padding:2px 7px;border-radius:3px;font-size:11px;font-weight:600;white-space:nowrap}
.tag.red{background:#fdecea;color:var(--red)}
.tag.amber{background:#fef6e7;color:var(--amber)}
.tag.gray{background:#f0f0f1;color:#777}
.tag.blue{background:#eaf2fb;color:var(--blue)}

.rule-main{font-weight:500}
.rule-sub{color:var(--muted);font-size:12px;margin-top:5px}
.rule-sub b{color:#555;font-weight:600}
.rule-ex{margin-top:7px;font-size:12px;line-height:1.7}
.rule-ex .no{color:var(--red)}
.rule-ex .yes{color:var(--green)}
.rule-ex .no::before{content:"✗ 不要写：";font-weight:600}
.rule-ex .yes::before{content:"✓ 应该写：";font-weight:600}
.rule-ex div{margin-top:2px}

.conflict{border:1px solid #f0e0bd;background:#fffdf5;border-radius:6px;padding:14px 16px;margin-bottom:12px}
.conflict h3{margin:0 0 8px;font-size:13px}
.conflict .detail{font-size:12px;color:#7a5c1e;margin:0 0 10px;line-height:1.7}
.parties{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.party{background:#fff;border:1px solid #eee6d5;border-radius:5px;padding:10px 12px}
.party label{display:block;font-size:11px;color:#999;margin-bottom:4px}
.party p{margin:0;font-size:12px;line-height:1.6}
.party small{display:block;margin-top:5px;color:#aaa;font-size:11px}

.excluded td{color:var(--muted);font-size:12px}
.foot{margin-top:40px;padding-top:16px;border-top:1px solid var(--line);
  color:#999;font-size:11px;line-height:1.8}
.empty{color:var(--muted);font-size:13px;padding:12px 0}

@media print{
  @page{size:A4;margin:14mm 12mm}
  body{background:#fff;font-size:11px}
  .page{padding:0;max-width:none}
  h2{break-after:avoid}
  table{break-inside:auto}
  tr{break-inside:avoid}
  .conflict{break-inside:avoid}
}
@media(max-width:760px){.page{padding:24px 18px}.parties{grid-template-columns:1fr}}
"""


def build(doc):
    meta = doc.get("meta") or {}
    rules = doc.get("rules") or []
    conflicts = doc.get("conflicts") or []
    not_rules = doc.get("not_rules") or []

    client = meta.get("client_name") or meta.get("client_id") or ""
    short = meta.get("client_short") or client
    version = meta.get("version") or ""
    is_draft = "draft" in version
    ext = meta.get("extraction") or {}
    sources = ext.get("source_files") or []

    # 按 polarity 分组：业务脑子里的分类是「不能/必须/允许/建议」
    groups = {"must_not": [], "must": [], "may": [], "prefer": []}
    for r in rules:
        p = r.get("polarity") or "must"
        groups.setdefault(p, []).append(r)
    for k in groups:
        # 拒稿线排前面
        order = {"reject": 0, "fix": 1, "advise": 2}
        groups[k].sort(key=lambda x: (order.get(x.get("severity"), 9), x.get("id", "")))

    out = []
    A = out.append

    A(f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(short)} 写作规则确认单</title><style>{CSS}</style></head><body><div class="page">""")

    A(f"""<h1>{esc(client)} 写作规则确认单</h1>
<p class="lead">这份文件列出系统从客户资料中整理出的全部写作要求，用于和业务确认口径。</p>
<p class="lead">请重点看两部分：<b>需要您拍板的问题</b>（客户资料之间互相矛盾）和 <b>不能/必须</b> 两节。</p>
<div class="meta">规则包 {esc(version)}　·　共 {len(rules)} 条　·　生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>""")

    # ---- 需要拍板 ----
    A(f'<h2>一、需要您拍板的问题<span class="count">{len(conflicts)} 处</span></h2>')
    if conflicts:
        A('<p class="hint">客户提供的资料之间有互相矛盾的地方，系统没有替您做决定。请确认最终按哪个口径执行。</p>')
        for i, c in enumerate(conflicts, 1):
            A(f'''<div class="conflict">
<h3>{i}. {esc(c.get("topic"))}</h3>
<p class="detail">{esc(c.get("detail"))}</p>
<div class="parties">
  <div class="party"><label>口径 A</label><p>{esc(c.get("party_a"))}</p><small>出自：{esc(c.get("from_a"))}</small></div>
  <div class="party"><label>口径 B</label><p>{esc(c.get("party_b"))}</p><small>出自：{esc(c.get("from_b"))}</small></div>
</div></div>''')
    else:
        A('<p class="empty">没有发现互相矛盾的资料。</p>')

    # ---- 分组规则 ----
    section_no = {"must_not": "二", "must": "三", "may": "四", "prefer": "五"}
    for pol in ("must_not", "must", "may", "prefer"):
        items = groups.get(pol) or []
        title, _ = POLARITY_LABEL[pol]
        A(f'<h2>{section_no[pol]}、{title}<span class="count">{len(items)} 条</span></h2>')
        if not items:
            A('<p class="empty">无。</p>')
            continue

        A('<table><thead><tr><th class="col-no">#</th><th>要求</th>'
          '<th class="col-tag">严重度</th><th class="col-tag">执行方式</th>'
          '<th class="col-from">客户原文出处</th></tr></thead><tbody>')

        for i, r in enumerate(items, 1):
            sev = SEVERITY_LABEL.get(r.get("severity"), ("", "gray"))
            enf = ENFORCE_LABEL.get(r.get("enforcement"), r.get("enforcement") or "")
            cat = CATEGORY_LABEL.get(r.get("category"), r.get("category") or "")

            body = [f'<div class="rule-main">{esc(r.get("statement"))}</div>']
            if r.get("condition"):
                body.append(f'<div class="rule-sub"><b>适用场景：</b>{esc(r["condition"])}</div>')
            if r.get("alternative"):
                body.append(f'<div class="rule-sub"><b>改法：</b>{esc(r["alternative"])}</div>')
            if r.get("scope_note"):
                first = str(r["scope_note"]).strip().split("\n")[0]
                if len(first) > 100:
                    first = first[:100] + "…"
                body.append(f'<div class="rule-sub"><b>边界：</b>{esc(first)}</div>')
            for ex in (r.get("examples") or [])[:2]:
                if ex.get("wrong") or ex.get("right"):
                    parts = ['<div class="rule-ex">']
                    if ex.get("wrong"):
                        parts.append(f'<div class="no">{esc(ex["wrong"])}</div>')
                    if ex.get("right"):
                        parts.append(f'<div class="yes">{esc(ex["right"])}</div>')
                    parts.append("</div>")
                    body.append("".join(parts))

            A(f'''<tr>
<td class="col-no">{i}</td>
<td>{"".join(body)}<div class="rule-sub" style="color:#aaa">{esc(cat)}</div></td>
<td class="col-tag"><span class="tag {sev[1]}">{sev[0]}</span></td>
<td class="col-tag" style="font-size:12px;color:#666">{esc(enf)}</td>
<td class="col-from">{esc(r.get("source_file") or r.get("evidence") or "")}</td>
</tr>''')
        A("</tbody></table>")

    # ---- 没被当成规则的内容 ----
    if not_rules:
        A(f'<h2>六、没有当成写作要求的内容<span class="count">{len(not_rules)} 项</span></h2>')
        A('<p class="hint">这些内容来自客户资料，但判断为企业事实或素材，归知识库管理，不写进工作流。列出来供您核对，避免以为漏掉了。</p>')
        A('<table class="excluded"><thead><tr><th>内容</th><th>为什么不算写作要求</th></tr></thead><tbody>')
        for n in not_rules:
            A(f'<tr><td>{esc(n.get("content"))}</td><td>{esc(n.get("why"))}</td></tr>')
        A("</tbody></table>")

    # ---- 脚注 ----
    src_txt = "、".join(sources) if sources else "未记录"
    draft_note = ("<b>当前是草稿版本。</b>系统抽取可能有遗漏或归类偏差，确认后才能用于正式生文。"
                  if is_draft else "")
    A(f'''<div class="foot">
<p>{draft_note}</p>
<p>来源资料：{esc(src_txt)}</p>
<p>「系统自动检查」的条目会在生文后被程序直接检出；「模型判断」的条目由模型结合上下文判断；「人工把关」的条目需要在流程上落实。</p>
<p>标为「建议」的条目不计入合格率，只作为写作方向参考。</p>
</div>''')

    A("</div></body></html>")
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rules")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    doc = yaml.safe_load(Path(args.rules).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(doc), encoding="utf-8")
    print(f"已导出: {out}（{out.stat().st_size // 1024} KB）")


if __name__ == "__main__":
    main()
