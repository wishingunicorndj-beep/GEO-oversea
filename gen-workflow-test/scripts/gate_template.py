#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""N8-pre 代码门禁的生成模板。

独立成文件的原因：这里要拼出「写进 yml 的 Python 源码」，用 f-string 需要把所有
字典和花括号写成 {{ }}，加一个函数就得全篇转义，极易写错。改用普通 raw 字符串
+ 占位符替换，生成出来的代码与这里读到的完全一致。

占位符：
  __GATE_JSON__  规则包抽出的确定性规则（JSON）
"""

GATE_MODULE = r'''
# ---------------------------------------------------------------------------
# 客户规则代码门禁（由 build_client_workflow.py 从规则包生成，勿手改）
# 只做可确定性检出的规则；语义类规则由 LLM 节点执行。
# 命中一律写进 gate_report 供业务查看；只有客户明确要求「删掉」的下架产品会真删句子，
# 其余命中只标注，避免按关键词误删正文（块级误删教训）。
# 替换类规则（旧品牌名→现品牌名）会真的改文本，并逐条记录命中。
# ---------------------------------------------------------------------------
GATE = json.loads(r"""__GATE_JSON__""")

CONTACT_WHITELIST = [c.replace(' ', '').replace('-', '')
                     for c in (GATE.get('contact_whitelist') or []) if c]
# 母版只认「联系电话/联系方式/咨询电话/扫码添加」四种写法，
# 「报名电话」「招生电话」「客服电话」这类常见变体会漏网，这里补齐。
_CONTACT_KEYWORDS = ('联系电话|联系方式|咨询电话|报名电话|招生电话|客服电话|服务电话'
                     '|咨询热线|热线电话|垂询电话|预约电话|联系电话|扫码添加|添加微信|微信号')
CONTACT_RE = re.compile(r'(?i)(?:' + _CONTACT_KEYWORDS +
                        r')[：:：]?\s*[^<。！？\n]{0,80}')
# 号码本身也要兜：没有关键词、只写一串手机号/400 电话的同样按母版原意删除
BARE_PHONE_RE = re.compile(r'(?<!\d)(?:1[3-9]\d{9}|400[-\s]?\d{3}[-\s]?\d{4}'
                           r'|0\d{2,3}[-\s]?\d{7,8})(?!\d)')
REPLACEMENTS = sorted(GATE.get('replacements') or [],
                      key=lambda r: -len(str(r.get('from') or '')))


def _strip_contacts(text):
    """删除联系方式，但保留客户要求必带的统一电话。

    母版无条件删除「联系电话：…」整段，会把客户要求每篇都加的统一电话一并删掉。
    这里按段判断：含白名单号的段保留，其余按母版原意删除。
    删完清掉悬空动词（「可拨打。」）与被打空的容器（`<ul></ul>`），不留残段。
    """
    text = str(text or '')
    if not CONTACT_WHITELIST:
        return CONTACT_RE.sub('', text)

    def _flat(value):
        return value.replace(' ', '').replace('-', '')

    def _keep(seg):
        flat = _flat(seg)
        return any(w and w in flat for w in CONTACT_WHITELIST)

    def _strip_seg(m):
        seg = m.group(0)
        return seg if _keep(seg) else ''

    def _clean_block(m):
        block = m.group(0)
        stripped = CONTACT_RE.sub(_strip_seg, block)
        # 关键词变体之外，裸写的手机号/400 也删（白名单号不动）
        stripped = BARE_PHONE_RE.sub(
            lambda mm: mm.group(0) if _keep(mm.group(0)) else '', stripped)
        if stripped == block:
            return block
        # 删号码后留下「…可拨打。」这类悬空动词，一并去掉
        stripped = re.sub(r'(?:如需|想要|可|请|欢迎)'
                          r'(?:拨打|联系|致电|来电|垂询|添加|扫码)[，、；]?[。.!?]?\s*(?=</)', '',
                          stripped)
        # 句末残留的逗号/顿号收掉，避免「如需了解课程详情，</p>」
        stripped = re.sub(r'[，、；：,;:]\s*(?=</)', '', stripped)
        stripped = re.sub(r'([，、；：,;:])\s*(?=[。！？.!?])', '', stripped)
        bare = re.sub(r'[，。、；：,.;:！？!?\s]', '', re.sub(r'<[^>]+>', '', stripped))
        return stripped if len(bare) > 6 else ''

    out = re.sub(r'<(?P<tag>p|li|div|span|td|h[1-6])\b[^>]*>.*?</(?P=tag)>',
                 _clean_block, text, flags=re.I | re.S)
    out = CONTACT_RE.sub(_strip_seg, out)
    out = BARE_PHONE_RE.sub(lambda mm: mm.group(0) if _keep(mm.group(0)) else '', out)
    # 删除后变空的容器一并去掉
    out = re.sub(r'<(ul|ol|div|section)\b[^>]*>\s*</\1>', '', out, flags=re.I)
    out = re.sub(r'(?m)^[ \t]*[，。、；：,.;:！？!?]+[ \t]*$', '', out)
    return out


def _apply_replacements(text):
    """按客户的旧→新对照表自动替换，返回 (新文本, 命中清单)。

    长模式优先，避免「新东方素质成长中心数学课程包括脑力与思维」被短模式先切走一半。
    替换词自身以「课程」结尾时，正文若已紧跟「课程」就去重，避免写出「…课程课程」。
    """
    hits = []
    out = str(text or '')
    if not REPLACEMENTS or not out:
        return out, hits
    for rule in REPLACEMENTS:
        src = str(rule.get('from') or '')
        dst = str(rule.get('to') or '')
        if not src or not dst or src not in out:
            continue
        if dst.endswith('课程'):
            def _rep(m, dst=dst):
                tail = m.string[m.end():m.end() + 2]
                return dst[:-2] if tail == '课程' else dst
            out, n = re.subn(re.escape(src), _rep, out)
        else:
            n = out.count(src)
            out = out.replace(src, dst)
        if n:
            hits.append({'id': rule.get('id') or 'REPLACE',
                         'from': src, 'to': dst, 'count': n})
    return out, hits


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


def _brand_combo_hits(text):
    """检出「品牌名紧跟学科名」的组合写法，如「新东方素质成长中心数学」。"""
    conf = GATE.get('brand_combo') or {}
    brands = [b for b in (conf.get('brands') or []) if b]
    subjects = [s for s in (conf.get('subjects') or []) if s]
    if not brands or not subjects:
        return []
    brand_alt = '|'.join(re.escape(b) for b in sorted(brands, key=len, reverse=True))
    subj_alt = '|'.join(re.escape(s) for s in sorted(subjects, key=len, reverse=True))
    out = []
    for m in re.finditer('(?:%s)(?:%s)' % (brand_alt, subj_alt), str(text or '')):
        got = m.group(0)
        if got not in out:
            out.append(got)
    return out


def _required_check(title, body):
    """客户要求「每篇尽量出现」的要素，缺失时报 warn，不阻断。"""
    issues = []
    for rule in GATE.get('required') or []:
        patterns = rule.get('patterns') or []
        if not patterns:
            continue
        try:
            found = any(re.search(p, body or '') or re.search(p, title or '')
                        for p in patterns)
        except re.error:
            found = False
        if found:
            continue
        issues.append({'id': rule.get('id') or 'REQUIRED',
                       'level': rule.get('level') or 'warn',
                       'field': 'body',
                       'hits': [rule.get('label') or ''],
                       'action': rule.get('action') or '缺客户要求出现的要素'})
    return issues


def _faq_check(content):
    """FAQ 编号须从 Q1 起连续。只报告，不改写（缺标题无法确定性地补）。"""
    nums = [int(m.group(1)) for m in re.finditer(r'(?<![A-Za-z])[Qq]\s*(\d+)(?=[：:.．、\s])', content)]
    if not nums:
        return None
    expect = list(range(nums[0], nums[0] + len(nums)))
    if nums[0] == 1 and nums == list(range(1, len(nums) + 1)):
        return None
    if nums == expect:
        return {'id': 'FAQ', 'level': 'hard', 'field': 'body',
                'hits': ['Q%d 起' % nums[0]],
                'action': 'FAQ 编号未从 Q1 开始，需补齐首组问答标题'}
    return {'id': 'FAQ', 'level': 'hard', 'field': 'body',
            'hits': [','.join('Q%d' % n for n in nums)],
            'action': 'FAQ 编号不连续，需补齐缺失的问题标题'}


def _place_tokens(text):
    """从「分布于/覆盖/位于/布局于…」后的枚举里提取地名候选。

    正文与知识库走同一套提取逻辑，保证两侧对称，避免单侧口径差异导致误报。
    只取 2-4 字纯汉字，去掉「等城市/等地区/等/城市/市」等尾巴。
    """
    out = []
    for m in re.finditer(r'(?:分布于|分布|覆盖|位于|布局于|布局|落地|进驻)([^。；;\n]{2,120})', str(text or '')):
        for tok in re.split(r'[、，,]', m.group(1)):
            tok = re.sub(r'(?:等城市|等地区|等地|等|城市|地区|市)$', '', tok.strip())
            tok = re.sub(r'^[的及和与]', '', tok)
            if re.fullmatch(r'[\u4e00-\u9fa5]{2,4}', tok):
                out.append(tok)
    return out


def _place_check(body, kb_text):
    """找出正文枚举里、知识库完全没有出处的城市（防编造地名）。

    只在同一批提取结果里已有多数地名能在知识库找到时才判定，
    避免把业态枚举（写字楼、酒店）误当地名列表。
    """
    kb_places = set(_place_tokens(kb_text))
    if not kb_places:
        return []
    places = _place_tokens(body)
    known = [p for p in places if p in kb_places]
    if len(known) < 2:
        return []
    unknown = []
    for p in places:
        if p not in kb_places and p not in unknown:
            unknown.append(p)
    if not unknown:
        return []
    return [{'id': 'PLACE', 'level': 'hard', 'field': 'body',
             'hits': unknown,
             'action': '地名在知识库中无出处，需删除或核实'}]


def _apply_gate(art, kb_text=''):
    """在清洗后的文章上执行确定性检查。只标注、定向删除与客户要求的替换。"""
    issues = []
    title = str(art.get('title') or '')
    content = str(art.get('content') or '')

    title, title_repl = _apply_replacements(title)
    content, body_repl = _apply_replacements(content)
    for h in title_repl:
        issues.append({'id': h['id'], 'level': 'info', 'field': 'title',
                       'hits': [h['from'] + ' → ' + h['to']],
                       'action': '客户要求的旧表述已自动替换'})
    for h in body_repl:
        issues.append({'id': h['id'], 'level': 'info', 'field': 'body',
                       'hits': [h['from'] + ' → ' + h['to']],
                       'action': '客户要求的旧表述已自动替换'})

    body = _strip_tags(content)

    for rule in GATE.get('title_terms', []):
        hit = _hits(title, rule['terms'])
        if hit:
            issues.append({'id': rule['id'], 'level': 'hard', 'field': 'title',
                           'hits': hit,
                           'action': rule.get('action') or '标题命中客户禁用词'})

    for rule in GATE.get('body_terms', []):
        hit = _hits(body, rule['terms'])
        if hit:
            issues.append({'id': rule['id'], 'level': 'hard', 'field': 'body',
                           'hits': hit,
                           'action': rule.get('action') or '正文命中客户禁用词'})

    for rule in GATE.get('title_regex', []):
        hit = _regex_hits(title, rule['patterns'])
        if hit:
            issues.append({'id': rule['id'], 'level': rule.get('level') or 'hard',
                           'field': 'title',
                           'hits': hit,
                           'action': rule.get('action') or '标题命中客户禁用模式'})

    for rule in GATE.get('body_regex', []):
        hit = _regex_hits(body, rule['patterns'])
        if hit:
            issues.append({'id': rule['id'], 'level': rule.get('level') or 'hard',
                           'field': 'body',
                           'hits': hit,
                           'action': rule.get('action') or '正文命中客户禁用模式'})

    combo_hit = _brand_combo_hits(title) + [h for h in _brand_combo_hits(body)
                                            if h not in _brand_combo_hits(title)]
    if combo_hit:
        issues.append({'id': (GATE.get('brand_combo') or {}).get('id') or 'COMBO',
                       'level': 'hard', 'field': 'title,body',
                       'hits': combo_hit,
                       'action': '出现「品牌名+学科名」组合写法，需拆开或改用课程名'})

    for entry in GATE.get('product_names', []):
        names = [entry.get('name') or ''] + list(entry.get('aliases') or [])
        hit = next((n for n in names if n and n in body), '')
        if not hit:
            continue
        issues.append({'id': 'PRODUCT', 'level': 'hard', 'field': 'body',
                       'hits': [hit], 'action': '含客户禁提产品，已删除相关句子'})
        parts = re.split(r'(?<=[。！？\n])', content)
        content = ''.join(p for p in parts if hit not in _strip_tags(p))
        body = _strip_tags(content)

    if GATE.get('check_faq_numbering'):
        issue = _faq_check(content)
        if issue:
            issues.append(issue)

    if GATE.get('check_place_enumeration'):
        issues.extend(_place_check(body, kb_text))

    issues.extend(_required_check(title, body))

    out = dict(art)
    out['title'] = title
    out['content'] = content
    if issues:
        summary = '；'.join("%s:%s" % (i['id'], '/'.join(i['hits'])) for i in issues)
        out['self_review'] = (str(out.get('self_review') or '') + '\n[门禁] ' + summary).strip()
    return out, issues


def main(articles=None, ent_body='', prod_body=''):
    if not isinstance(articles, list):
        return {'cleaned_articles': [], 'gate_report': []}
    kb_text = str(ent_body or '') + '\n' + str(prod_body or '')
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
            first = re.sub(r'<[^>]+>', '', content).strip().split('\n')[0]
            title = first[:40]
        if not content: continue
        item = {'title': title, 'description': description, 'content': content,
                'tags': tags, 'self_review': review}
        item, issues = _apply_gate(item, kb_text)
        cleaned.append(item)
        if issues:
            report.append({'title': item.get('title', ''), 'issues': issues})
    return {'cleaned_articles': cleaned, 'gate_report': report}
'''
