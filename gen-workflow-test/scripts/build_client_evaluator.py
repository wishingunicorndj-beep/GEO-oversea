#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据客户规则包生成质量评估器。

设计要点：
  1. 评估只对 must / must_not 生效；may / prefer 不进合格率，单列建议项。
  2. code 类规则用确定性代码判，结果永远可复现。
  3. llm 类规则批量判定：一篇文章一次调用覆盖多条规则，强制引用原文证据句。
     不做 1-10 打分——打分不可复现，无法用于回归。
  4. 证据句需能在原文逐字找到，否则降级 unclear，防止模型编造。
  5. 整批另算重复度指标（标题同质、H2 骨架重合、句子复用），纯代码可复现。

用法：
  python3 scripts/build_client_evaluator.py clients/前海人寿/rules.yaml
"""
import argparse
import json
import os

import yaml

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_rules(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def select_rules(rules):
    code_rules, llm_rules, skipped = [], [], []
    for r in rules["rules"]:
        pol = r.get("polarity")
        enf = r.get("enforcement")
        if pol not in ("must", "must_not"):
            skipped.append({"id": r["id"], "why": f"{pol} 类不进合格率", "statement": r.get("statement", "")})
            continue
        if enf == "human":
            skipped.append({"id": r["id"], "why": "人工流程项", "statement": r.get("statement", "")})
            continue
        if r.get("needs_source"):
            skipped.append({"id": r["id"], "why": "需对照知识库原文", "statement": r.get("statement", "")})
            continue
        if enf == "code" and r.get("detect"):
            code_rules.append({
                "id": r["id"], "statement": r.get("statement", ""),
                "severity": r.get("severity"), "polarity": pol,
                "detect": r["detect"], "scope": r.get("scope") or ["title", "body"],
            })
        else:
            llm_rules.append({
                "id": r["id"], "statement": r.get("statement", ""),
                "severity": r.get("severity"), "polarity": pol,
                "condition": r.get("condition"), "scope": r.get("scope") or ["title", "body"],
                "scope_note": r.get("scope_note") or "",
                "needs_source": bool(r.get("needs_source")),
            })
    return code_rules, llm_rules, skipped


TEMPLATE = r'''#!/usr/bin/env python3
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

SPEC = json.loads(r"""__SPEC__""")

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
'''


def render(rules, meta):
    code_rules, llm_rules, skipped = select_rules(rules)
    payload = {
        "client": meta.get("client_name"),
        "code_rules": code_rules,
        "llm_rules": llm_rules,
        "skipped": skipped,
    }
    return TEMPLATE.replace("__SPEC__", json.dumps(payload, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rules")
    ap.add_argument("--out", default=None)
    ap.add_argument("--chunk", type=int, default=None,
                    help="每篇文章每次判定的规则数；默认全部一次判定")
    args = ap.parse_args()

    rules = load_rules(args.rules)
    meta = rules.get("meta") or {}
    short = meta.get("client_short") or meta.get("client_name") or "client"
    out = args.out or os.path.join(BASE, "clients", short, "evaluate.py")

    code, llm, skipped = select_rules(rules)
    src = render(rules, meta)

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"已生成评估器: {out}")
    print(f"  代码可判 {len(code)} 条 / 需模型判 {len(llm)} 条 / 不进评估 {len(skipped)} 条")
    print(f"  判定批次: 1 篇文章 × 1 次调用覆盖 {len(llm)} 条规则（可用 --chunk 拆分）")


if __name__ == "__main__":
    main()
