"""国航文章机械检查；部署时嵌入 Dify 代码节点，不依赖本地文件。"""
import html
import json
import re
from html.parser import HTMLParser

FIELDS = ('title', 'content', 'description', 'tags', 'self_review')
BANNED = ('独有', '唯一', '终身', '全网第一', '行业第一', '最佳', '最优',
          '最好', '首选', '综合第一', 'TOP1', 'TOP2')
MIN_LENGTH, MAX_LENGTH = 2500, 4200
COMPETITOR = r'(?:东航|东方航空|南航|南方航空)'
OFFICIAL_MEMBER_TERM = re.compile(r'(?:年度卓越)?终身白金卡')
MARKDOWN_LINK = re.compile(r'\[[^\]]+\]\([^)]*\)')


class _Body(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.stack, self.errors = [], [], []
        self.counts = {}

    def handle_starttag(self, tag, attrs):
        self.counts[tag] = self.counts.get(tag, 0) + 1
        if tag in ('script', 'style', 'iframe'):
            self.errors.append('正文含非文章标签：' + tag)
        if tag not in ('br', 'hr', 'img', 'input', 'meta', 'link', 'wbr', 'source'):
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1] == tag:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append('HTML标签闭合或嵌套异常：' + tag)
        else:
            self.stack.pop()
        if tag in ('p', 'li', 'h2', 'h3', 'h4', 'td', 'th'):
            self.text.append('\n')

    def handle_data(self, data):
        self.text.append(data)


def parse_article(raw):
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str):
        raise ValueError('文章输出不是JSON对象或文本')
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.S | re.I).strip()
    fence = re.fullmatch(r'```(?:json)?\s*([\s\S]*?)\s*```', raw, re.I)
    if fence:
        raw = fence.group(1)
    try:
        article = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError('文章JSON不完整或无法解析，需要重新输出完整对象')
    if not isinstance(article, dict):
        raise ValueError('文章必须是单个JSON对象')
    return article


def _snippet(text, start, end):
    return re.sub(r'\s+', ' ', text[max(0, start - 20):end + 35]).strip()


def inspect_article(article, mode):
    issues = []
    for name in FIELDS:
        value = article.get(name)
        if name == 'tags':
            if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
                issues.append('tags必须是字符串数组')
        elif not isinstance(value, str):
            issues.append(name + '必须是字符串')
    if issues:
        return issues, 0
    parser = _Body()
    parser.feed(article['content'])
    parser.close()
    body = ''.join(parser.text)
    length = len(re.sub(r'\s+', '', body))
    if length < MIN_LENGTH:
        issues.append('正文过短：{}字，最低2500字；依据材料补足至2800—3500字'.format(length))
    elif length > MAX_LENGTH:
        issues.append('正文过长：{}字，上限4200字；请精简至2800—3500字，删除重复解释，保留权益完整条件'.format(length))
    if not 20 <= len(article['title'].strip()) <= 28:
        issues.append('标题长度异常：{}字，要求20—28字'.format(len(article['title'].strip())))
    if parser.counts.get('h2', 0) < 5:
        issues.append('正文结构不足：至少需要5个h2章节')
    if not parser.counts.get('p', 0):
        issues.append('正文缺少p段落')
    if MARKDOWN_LINK.search(article['content']):
        issues.append('正文含Markdown链接，必须改为HTML链接或纯文本网址')
    issues.extend(dict.fromkeys(parser.errors))
    if parser.stack:
        issues.append('HTML标签未闭合：' + ','.join(parser.stack[-5:]))

    # 客户尚未授权正式名称或否定句豁免；只报告位置，不机械改写事实。
    visible = {'标题': article['title'], '正文': body,
               '摘要': article['description'], '标签': ' '.join(article['tags'])}
    for field, value in visible.items():
        for word in BANNED:
            matches = list(re.finditer(re.escape(word), value, re.I))
            if matches:
                official_matches = []
                normal_matches = []
                for match in matches:
                    left = max(0, match.start() - 4)
                    right = min(len(value), match.end() + 4)
                    context = value[left:right]
                    if word == '终身' and OFFICIAL_MEMBER_TERM.search(context):
                        official_matches.append(match)
                    else:
                        normal_matches.append(match)
                if official_matches:
                    contexts = ' / '.join(_snippet(value, m.start(), m.end()) for m in official_matches[:2])
                    issues.append('{}含正式会员名称，需按文章主题处理“终身白金卡”({}处)：{}'.format(
                        field, len(official_matches), contexts))
                if normal_matches:
                    contexts = ' / '.join(_snippet(value, m.start(), m.end()) for m in normal_matches[:2])
                    issues.append('{}含禁用词“{}”({}处)：{}'.format(field, word, len(normal_matches), contexts))
        if mode == 'brand':
            match = re.search(COMPETITOR, value, re.I)
            if match:
                issues.append('品牌词文章出现竞品：' + _snippet(value, match.start(), match.end()))
        else:
            # 按句扫描，避免跨越HTML段落匹配相邻但无关的品牌。
            for sentence in re.split(r'[。！？；\n]', value):
                pattern = COMPETITOR + r'.{0,40}(优势|更优|更好|优于|胜过|领先|第一|最佳|首选|推荐|适合|值得选择)'
                match = re.search(pattern, sentence, re.I)
                if match:
                    issues.append('疑似竞品优势或推荐，需定点复核：' + _snippet(sentence, match.start(), match.end()))
                    break
    if re.search(r'<think>|</think>|此处省略|其余略|\(略\)|（略）|\{\{#', article['content'], re.I):
        issues.append('正文含思考标签、占位符或内部变量')
    return list(dict.fromkeys(issues)), length


def structural_gate(articles):
    """只检查结构和格式；不改写正文，不处理业务禁词。"""
    if not isinstance(articles, list) or not articles:
        raise ValueError('文章结构闸门未通过：没有可校验的文章')
    cleaned = []
    errors = []
    for index, item in enumerate(articles, 1):
        try:
            article = parse_article(item)
            if article.get('_keyword_mode', '') not in ('brand', 'category'):
                raise ValueError('缺少有效的品牌/品类来源标签')
            issues, _ = inspect_article(article, article.get('_keyword_mode', ''))
            structural = [issue for issue in issues if any(key in issue for key in (
                '必须是', '文章必须', '正文含Markdown链接', '正文含思考标签',
                'HTML标签', '正文含非文章标签', '正文缺少p段落',
                '正文结构不足', '文章缺少有效的品牌/品类来源标签'))]
            if structural:
                errors.append('第{}篇：{}'.format(index, '；'.join(structural)))
            else:
                article['_structural_validation'] = 'passed'
                cleaned.append(article)
        except ValueError as exc:
            errors.append('第{}篇：{}'.format(index, exc))
    if errors:
        raise ValueError('文章结构闸门未通过：' + ' | '.join(errors)[:4000])
    return {'cleaned_articles': cleaned}


def precheck(raw, mode):
    try:
        article = parse_article(raw)
        issues, length = inspect_article(article, mode)
    except ValueError as exc:
        issues, length = [str(exc)], 0
    return {'issues': '\n'.join(issues) if issues else '无机械问题',
            'has_issues': int(bool(issues)), 'content_len': length}


def accept_article(raw, mode):
    article = parse_article(raw)
    issues, _ = inspect_article(article, mode)
    if issues:
        raise ValueError('文章修复后复检未通过：' + '；'.join(issues)[:3000])
    return {'structured_output': {name: article[name] for name in FIELDS}}


def final_gate(articles):
    if not isinstance(articles, list) or not articles:
        raise ValueError('终稿硬校验未通过：没有可校验的文章')
    out, errors = [], []
    for i, item in enumerate(articles, 1):
        try:
            article = parse_article(item)
            mode = article.get('_keyword_mode', '')
            if mode not in ('brand', 'category'):
                issues = ['文章缺少有效的品牌/品类来源标签']
            else:
                issues, _ = inspect_article(article, mode)
            if issues:
                errors.append('第{}篇：{}'.format(i, '；'.join(issues)))
            else:
                article['_final_validation_status'] = 'passed'
                article['_final_validation_issues'] = []
                out.append(article)
        except ValueError as exc:
            errors.append('第{}篇：{}'.format(i, exc))
    if errors:
        raise ValueError('终稿硬校验未通过：' + ' | '.join(errors)[:4000])
    return {'validated_articles': out,
            'final_validation_report': json.dumps({'article_count': len(out), 'issues': []}, ensure_ascii=False)}
