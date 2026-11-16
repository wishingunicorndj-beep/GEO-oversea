#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一个批次的验收结果导出成业务可直接查看的看板。

产物是单个 HTML 文件，内联全部样式与数据，双击即可在浏览器打开，
不需要启动服务，可直接发给业务或客户。

设计取舍：
  - 业务关心「这批能不能交」，不关心 330 条逐项明细 → 首屏只放结论与问题清单
  - 违规必须带原文证据，业务要能自己核对，不能只给一个数字
  - 重复度单独一块，它和「合规」是两个维度，不能混进合格率
  - 明细折叠保留，需要深挖时能展开，但默认不打扰

用法：
  python3 scripts/export_board.py clients/<slug>/batches/<batch_id> --out /tmp/board.html
"""
import argparse
import html
import json
import re
from pathlib import Path


def esc(s):
    return html.escape(str(s if s is not None else ''), quote=True)


def pct(v, digits=0):
    try:
        return f"{float(v) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return '—'


CSS = """
:root{
  --bg:#f7f7f8;--surface:#fff;--muted:#f9f9fa;--border:#e5e5e5;
  --text:#202123;--text-muted:#6f7076;--text-subtle:#9a9ba1;
  --accent:#10a37f;--accent-soft:#e9f7f2;--danger:#d14343;
  --warn-bg:#fff7e6;--warn-text:#8a6d3b;--warn-strong:#a46b12;
  --shadow:0 1px 2px rgba(0,0,0,.04),0 8px 24px rgba(0,0,0,.035);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:14px/1.5 Inter,-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:32px 28px 56px}

.head{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;margin-bottom:24px}
.eyebrow{font-size:10px;font-weight:800;letter-spacing:.11em;text-transform:uppercase;color:var(--accent);margin-bottom:8px}
h1{margin:0;font-size:26px;line-height:1.2;letter-spacing:-.03em}
.sub{margin:9px 0 0;font-size:13px;color:var(--text-muted);line-height:1.6}
.brand{flex:none;text-align:right;font-size:11px;color:var(--text-subtle);line-height:1.7}

.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:17px 18px;box-shadow:var(--shadow)}
.stat label{display:block;font-size:12px;color:var(--text-muted)}
.stat strong{display:block;font-size:26px;line-height:1.2;margin:6px 0 2px;letter-spacing:-.02em}
.stat small{font-size:11px;color:var(--text-subtle)}
.stat.danger strong{color:var(--danger)}
.stat.good strong{color:var(--accent)}
.stat strong em{font-style:normal;font-size:14px;font-weight:600;color:var(--text-subtle);margin-left:2px}

.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;box-shadow:var(--shadow);margin-bottom:18px;overflow:hidden}
.card-head{padding:16px 18px;border-bottom:1px solid #ededed}
.card-head h2{margin:0;font-size:14px;font-weight:700}
.card-head p{margin:4px 0 0;font-size:12px;color:var(--text-muted)}
.card-body{padding:18px}

.verdict-box{display:flex;align-items:center;gap:12px;padding:14px 16px;border-radius:10px;margin-bottom:18px;font-size:13px;line-height:1.6}
.verdict-box.pass{background:var(--accent-soft);color:#0b6b52;border-left:3px solid var(--accent)}
.verdict-box.fail{background:#fdf1f0;color:#8a3b33;border-left:3px solid var(--danger)}
.verdict-box.warn{background:var(--warn-bg);color:var(--warn-text);border-left:3px solid #e6a23c}
.verdict-box b{font-weight:700}

.tag{display:inline-flex;align-items:center;border-radius:999px;padding:3px 8px;font-size:11px;font-weight:600;white-space:nowrap}
.tag.teal{background:var(--accent-soft);color:#087b5d}
.tag.red{background:#fff0f0;color:#c14343}
.tag.gray{background:#f0f0f1;color:#76777c}
.tag.amber{background:#fff6df;color:#a46b12}

table{width:100%;border-collapse:separate;border-spacing:0;text-align:left}
th{background:var(--muted);font-size:11px;font-weight:600;color:#8d8e93;letter-spacing:.04em;
  text-transform:uppercase;padding:10px 16px;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:12px 16px;border-top:1px solid #f0f0f0;font-size:13px;color:#55565b;vertical-align:top}
tbody tr:first-child td{border-top:0}

.issue{border:1px solid var(--border);border-radius:10px;margin-bottom:10px;overflow:hidden}
.issue:last-child{margin-bottom:0}
.issue-head{display:flex;align-items:center;gap:10px;padding:11px 14px;background:#fdf6f6;border-bottom:1px solid #f2e4e4}
.issue-head .idx{flex:none;font-size:11px;font-weight:700;color:var(--danger)}
.issue-head .title{flex:1;min-width:0;font-size:13px;font-weight:600;color:#3c3d42}
.issue-body{padding:12px 14px}
.issue-rule{font-size:12px;color:var(--text-muted);margin-bottom:8px}
.issue-rule code{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--text-subtle);margin-right:6px}
.evidence{font-size:12px;line-height:1.6;color:#7a4a4a;background:#fdf6f6;
  border-left:2px solid #e8b4b4;padding:8px 11px;border-radius:0 6px 6px 0}
.evidence::before{content:"原文：";font-weight:700;color:#a06a6a}

.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px}
.metric{background:var(--muted);border-radius:9px;padding:12px 14px}
.metric label{display:block;font-size:11px;color:var(--text-muted);margin-bottom:5px}
.metric strong{font-size:19px;font-weight:700}
.metric small{display:block;font-size:11px;color:var(--text-subtle);margin-top:3px}
.metric.warn strong{color:var(--warn-strong)}
.warn-list{display:grid;gap:7px;margin:0;padding:0;list-style:none}
.warn-list li{display:flex;gap:8px;font-size:13px;color:var(--warn-text);background:var(--warn-bg);border-radius:8px;padding:9px 12px;line-height:1.5}
.warn-list li::before{content:"!";flex:none;width:16px;height:16px;border-radius:50%;background:#e6a23c;color:#fff;font-size:11px;font-weight:800;display:grid;place-items:center}

details.art{border-top:1px solid #f0f0f0}
details.art:first-of-type{border-top:0}
details.art>summary{display:flex;align-items:center;gap:10px;padding:11px 18px;cursor:pointer;list-style:none;font-size:13px}
details.art>summary::-webkit-details-marker{display:none}
details.art>summary:hover{background:var(--muted)}
details.art>summary::before{content:"▸";font-size:11px;color:var(--text-subtle);width:10px}
details.art[open]>summary::before{content:"▾"}
details.art>summary .t{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#3c3d42}
.badges{display:flex;gap:5px;flex:none}

.foot{font-size:11px;line-height:1.7;color:var(--text-subtle)}
.foot p{margin:0 0 6px}
@media(max-width:860px){
  .stats,.metrics{grid-template-columns:repeat(2,1fr)}
  .head{display:block}
  .brand{text-align:left;margin-top:12px}
}
@page{size:A4;margin:14mm 12mm}
@media print{
  body{background:#fff;font-size:12px}
  .wrap{padding:0;max-width:none}
  .head{margin-bottom:16px}
  h1{font-size:20px}
  .sub{font-size:11px}
  .brand{font-size:10px}
  .stats{gap:8px;margin-bottom:12px}
  .stat{padding:12px 14px;box-shadow:none;border-color:#ddd}
  .stat strong{font-size:20px}
  .card{box-shadow:none;break-inside:avoid;margin-bottom:12px}
  .card-head{padding:12px 14px}
  .card-body{padding:14px}
  .issue{break-inside:avoid}
  .verdict-box{break-inside:avoid}
  th{font-size:9px;padding:7px 10px}
  td{font-size:10px;padding:7px 10px}
  .tag{font-size:9px}
  details.art{break-inside:avoid}
  details.art>summary{font-size:11px;padding:8px 14px}
  /* 打印时默认展开明细，否则 PDF 里只有标题 */
  details.art{display:block}
  details.art>div{display:block!important}
  .foot{font-size:9px}
}
"""


def build(report, meta=None):
    s = report.get('summary') or {}
    d = report.get('dedup') or {}
    arts = report.get('articles') or []
    client = report.get('client_short') or report.get('client') or ''
    label = report.get('batch_label') or report.get('batch_id') or '验收报告'
    judged = s.get('judged') or 0
    total = s.get('total') or 0
    violate = s.get('violate') or 0
    hard = s.get('hard_violate') or 0
    unclear = s.get('unclear') or 0

    # 结论判定：拒稿级 >0 判不通过；有违反判需修改；否则通过
    if hard > 0:
        box = ('fail', f'<b>本批存在 {hard} 处拒稿级问题，不能直接发布。</b>'
                      f' 另有 {violate - hard} 处需修改项，详见下方问题清单。')
    elif violate > 0:
        box = ('warn', f'<b>本批有 {violate} 处需修改，无拒稿级问题。</b>'
                      f' 修改后可进入人工复核环节。')
    else:
        box = ('pass', '<b>本批未发现规则违反，可通过验收。</b>'
                       ' 仍需人工复核确认表达质量。')

    # 问题清单：收集所有 violate
    issues = []
    for a in arts:
        for r in (a.get('rows') or []):
            if r.get('verdict') == 'violate':
                issues.append((a, r))

    issue_html = ''
    if issues:
        blocks = []
        for a, r in issues:
            blocks.append(
                '<div class="issue">'
                f'<div class="issue-head"><span class="idx">第 {a.get("index", 0) + 1} 篇</span>'
                f'<span class="title">{esc(a.get("title", ""))}</span>'
                f'<span class="tag red">违反</span></div>'
                '<div class="issue-body">'
                f'<div class="issue-rule"><code>{esc(r.get("rule_id", ""))}</code>{esc(r.get("statement", ""))}</div>'
                + (f'<div class="evidence">{esc(r.get("evidence", ""))}</div>' if r.get('evidence') else '')
                + '</div></div>')
        issue_html = '<div class="card"><div class="card-head"><h2>需要修改的问题</h2>' \
                     f'<p>共 {len(issues)} 处，均附原文证据，可在文章中直接检索定位</p></div>' \
                     f'<div class="card-body">{"".join(blocks)}</div></div>'
    else:
        issue_html = '<div class="card"><div class="card-head"><h2>需要修改的问题</h2>' \
                     '<p>本批未发现规则违反</p></div></div>'

    # 重复度
    warnings = d.get('warnings') or []
    metrics_html = (
        '<div class="metrics">'
        f'<div class="metric"><label>不同标题核心</label><strong>{d.get("title_distinct", 0)} / {d.get("article_count", 0)}</strong>'
        '<small>标题骨架唯一度</small></div>'
        f'<div class="metric{" warn" if (d.get("h2_overlap_max") or 0) >= .7 else ""}"><label>章节骨架重合（最高）</label>'
        f'<strong>{pct(d.get("h2_overlap_max"))}</strong><small>平均 {pct(d.get("h2_overlap_avg"))}</small></div>'
        f'<div class="metric"><label>跨篇句子复用率</label><strong>{pct(d.get("sentence_reuse_ratio"))}</strong>'
        '<small>逐字重复的句子占比</small></div>'
        f'<div class="metric"><label>正文相似度（最高）</label><strong>{pct(d.get("body_similarity_max"))}</strong>'
        f'<small>平均 {pct(d.get("body_similarity_avg"))}</small></div>'
        '</div>')
    if warnings:
        metrics_html += '<ul class="warn-list">' + ''.join(f'<li>{esc(w)}</li>' for w in warnings) + '</ul>'

    # 逐篇明细（折叠）
    detail_rows = []
    for a in arts:
        rows = a.get('rows') or []
        bad = [r for r in rows if r.get('verdict') == 'violate']
        unc = [r for r in rows if r.get('verdict') == 'unclear']
        okc = len(rows) - len(bad) - len(unc)
        badges = f'<span class="tag teal">{okc} 符合</span>'
        if bad:
            badges += f'<span class="tag red">{len(bad)} 违反</span>'
        if unc:
            badges += f'<span class="tag gray">{len(unc)} 未判定</span>'
        VLABEL = {'pass': '符合', 'violate': '违反', 'unclear': '未判定'}
        VTAG = {'pass': 'teal', 'violate': 'red', 'unclear': 'gray'}

        def _row(r):
            v = r.get('verdict') or 'unclear'
            return ('<tr>'
                    '<td><span style="font-family:ui-monospace,Menlo,monospace;font-size:11px;color:#9a9ba1">'
                    + esc(r.get('rule_id')) + '</span>'
                    '<div style="margin-top:3px">' + esc(r.get('statement')) + '</div></td>'
                    '<td>' + esc(r.get('category_label') or '') + '</td>'
                    '<td><span class="tag ' + VTAG.get(v, 'gray') + '">'
                    + VLABEL.get(v, '—') + '</span></td>'
                    '<td>' + esc(r.get('evidence') or '') + '</td>'
                    '</tr>')

        body = ''.join(_row(r) for r in rows)
        detail_rows.append(
            f'<details class="art"><summary><span class="t">第 {a.get("index", 0) + 1} 篇 · {esc(a.get("title", ""))}</span>'
            f'<span class="badges">{badges}</span></summary>'
            '<div style="overflow-x:auto"><table><thead><tr><th>客户要求</th><th>类别</th><th>判定</th><th>证据</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div></details>')

    return f"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(client)} 生文验收 · {esc(label)}</title>
<style>{CSS}</style>
</head><body><div class="wrap">

<div class="head">
  <div>
    <div class="eyebrow">ACCEPTANCE REPORT</div>
    <h1>{esc(label)}</h1>
    <p class="sub">{esc(client)} · {report.get('article_count', 0)} 篇文章 · 规则包 {esc(report.get('rules_version', '—'))} · 评估于 {esc(report.get('evaluated_at', ''))}</p>
  </div>
  <div class="brand">生文质量验收看板<br>本报告基于当时规则包快照生成</div>
</div>

<div class="verdict-box {box[0]}">{box[1]}</div>

<div class="stats">
  <div class="stat"><label>本批文章</label><strong>{report.get('article_count', 0)}<em>篇</em></strong><small>同一批次产出</small></div>
  <div class="stat {'danger' if violate else 'good'}"><label>需要修改</label><strong>{violate}<em>处</em></strong><small>{len(set(a.get('index') for a, _ in issues))} 篇涉及</small></div>
  <div class="stat {'danger' if hard else 'good'}"><label>其中拒稿级</label><strong>{hard}<em>处</em></strong><small>不可直接发布</small></div>
  <div class="stat good"><label>合格率</label><strong>{s.get('pass_rate_of_judged', 0)}<em>%</em></strong><small>已判定 {judged} / {total} 项</small></div>
</div>

{issue_html}

<div class="card">
  <div class="card-head"><h2>批次同质化</h2><p>逐字未必重复，但结构雷同会让读者觉得是同一篇的改写版</p></div>
  <div class="card-body">{metrics_html}</div>
</div>

<div class="card">
  <div class="card-head"><h2>逐篇明细</h2><p>点击展开查看该篇的全部规则判定</p></div>
  {''.join(detail_rows)}
</div>

<div class="foot">
  <p>判定「未判定」共 {unclear} 项，表示该规则需要外部资料佐证，或模型给出的证据句无法在原文中逐字定位。</p>
  <p>合格率指规则合规度，不等同于文章质量。同质化指标与合规是两个维度，需分别看待。</p>
  <p>本报告基于规则包 {esc(report.get('rules_version', '—'))} 快照生成，后续规则变更不影响本批结论。</p>
</div>

</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_dir", help="批次目录，如 clients/<slug>/batches/<id>")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    bdir = Path(args.batch_dir)
    rp = bdir / "report.json"
    if not rp.exists():
        raise SystemExit(f"找不到 {rp}")
    report = json.loads(rp.read_text(encoding="utf-8"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(report), encoding="utf-8")
    print(f"已导出看板: {out}（{out.stat().st_size // 1024} KB）")


if __name__ == "__main__":
    main()
