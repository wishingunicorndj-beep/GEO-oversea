"""Run with python3 scripts/test_cn_html_platforms.py; Ruby supplies YAML parsing."""
import base64
import gzip
import json
import subprocess
import unittest
import zlib
from pathlib import Path


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / 'workflows/国内GEO离线数据监控.yml'
WORKFLOW = json.loads(subprocess.check_output(
    ['ruby', '-ryaml', '-rjson', '-e', 'puts JSON.generate(YAML.load_file(ARGV[0]))', str(WORKFLOW_PATH)],
    text=True,
))
NODES = {str(node['id']): node['data'] for node in WORKFLOW['workflow']['graph']['nodes']}
NAMESPACE = {}
exec(compile(NODES['1766746558988']['code'], 'html_extractor', 'exec'), NAMESPACE)
MAIN = NAMESPACE['main']
PARSER = NAMESPACE['MarkdownAnswerParser']
CLASSES = {
    'deepseek': 'ds-assistant-message-main-content',
    'yuanbao': 'hyc-content-md hyc-content-md-done',
    'zhipu': 'markdown-body',
    'doubao': 'md-box-root',
}


def wrap(body, platform='deepseek'):
    attributes = ' data-testid="message_text_content"' if platform == 'doubao' else ''
    return '<section data-message-role="assistant"><div class="' + CLASSES[platform] + '"' + attributes + '>' + body + '</div></section>'


def encode(html, codec='zlib'):
    payload = html.encode('utf-8')
    if codec == 'zlib':
        payload = zlib.compress(payload)
    elif codec == 'gzip':
        payload = gzip.compress(payload)
    elif codec == 'deflate':
        compressor = zlib.compressobj(wbits=-15)
        payload = compressor.compress(payload) + compressor.flush()
    return base64.b64encode(payload).decode('ascii')


class HtmlPlatformTests(unittest.TestCase):
    def test_supported_platforms(self):
        for platform in CLASSES:
            with self.subTest(platform=platform):
                self.assertEqual(MAIN(encode(wrap('<p>回答正文</p>', platform)), platform), {
                    'answer_raw_new': '回答正文', 'parse_status': 'success', 'parse_error': '',
                })

    def test_normalize_platform_id(self):
        self.assertEqual(MAIN(encode(wrap('正文')), ' DeepSeek ')['answer_raw_new'], '正文')

    def test_no_cross_platform_fallback(self):
        for source in CLASSES:
            for requested in CLASSES:
                if source == requested:
                    continue
                with self.subTest(source=source, requested=requested):
                    with self.assertRaisesRegex(ValueError, '不跨平台回退'):
                        MAIN(encode(wrap('正文', source)), requested)

    def test_pending_platforms(self):
        for platform in ('qianwen', 'yiyan', 'kimi'):
            with self.subTest(platform=platform):
                with self.assertRaisesRegex(ValueError, '尚未适配'):
                    MAIN(encode(wrap('不能替代其他平台')), platform)

    def test_missing_and_unknown_platform(self):
        for platform in ('', None, 'unrecognized'):
            with self.subTest(platform=platform):
                with self.assertRaisesRegex(ValueError, 'model_id'):
                    MAIN(encode(wrap('正文')), platform)

    def test_deepseek_thinking(self):
        html = '<div class="ds-think-content">思考内容</div>' + wrap('<p>回答</p><div class="ds-think-content"><p>内部思考</p></div>')
        self.assertEqual(MAIN(encode(html), 'deepseek')['answer_raw_new'], '回答')

    def test_yuanbao_boundaries(self):
        html = '<section data-message-role="user"><div class="hyc-content-md">用户问题</div></section>'
        html += wrap('<div class="think">思考内容</div><p>正文<sup class="cite">99</sup></p><section class="refs">参考列表</section>', 'yuanbao')
        self.assertEqual(MAIN(encode(html), 'yuanbao')['answer_raw_new'], '正文')

    def test_zhipu_thinking_and_user_markdown(self):
        html = '<section data-message-role="user"><div class="markdown-body">用户问题</div></section>'
        html += '<section data-message-role="assistant"><div class="thinking-group"><div class="thinking-body"><div class="markdown-body">思考内容</div></div></div><div class="markdown-body"><p>最终回答</p></div></section>'
        self.assertEqual(MAIN(encode(html), 'zhipu')['answer_raw_new'], '最终回答')

    def test_zhipu_requires_assistant_ancestor(self):
        with self.assertRaisesRegex(ValueError, '未找到'):
            MAIN(encode('<div class="markdown-body">未确认角色</div>'), 'zhipu')

    def test_doubao_same_container_for_user_and_assistant(self):
        html = '<section data-message-role="user"><div class="md-box-root" data-testid="message_text_content">用户问题</div></section>'
        html += wrap('<h3>规格怎么选</h3><p>回答正文</p>', 'doubao')
        self.assertEqual(MAIN(encode(html), 'doubao')['answer_raw_new'], '### 规格怎么选\n\n回答正文')

    def test_doubao_requires_both_markers_and_assistant_role(self):
        samples = [
            '<div class="md-box-root" data-testid="message_text_content">未知角色</div>',
            '<section data-message-role="assistant"><div class="md-box-root">没有正文标识</div></section>',
            '<section data-message-role="assistant"><div data-testid="message_text_content">没有正文类名</div></section>',
            wrap('用户问题', 'doubao').replace('data-message-role="assistant"', 'data-message-role="user"'),
            wrap('系统提示', 'doubao').replace('data-message-role="assistant"', 'data-message-role="system"'),
        ]
        for html in samples:
            with self.subTest(html=html):
                with self.assertRaisesRegex(ValueError, '不跨平台回退'):
                    MAIN(encode(html), 'doubao')

    def test_doubao_excludes_search_results_and_page_controls(self):
        html = '<nav>历史会话与侧边栏</nav><section data-message-role="assistant">'
        html += '<div data-plugin-identifier="block_type:10025 | search_query_result_block.search_type:1">搜索 4 个关键词，参考 17 篇资料'
        html += '<a data-thinking-box-tool-call="true">参考资料中的冠珠</a></div>'
        html += wrap('<p>真实回答</p>', 'doubao')
        html += '<div data-testid="message_action_bar">复制分享</div><div data-testid="suggest_message_list">推荐追问</div></section>'
        self.assertEqual(MAIN(encode(html), 'doubao')['answer_raw_new'], '真实回答')

    def test_doubao_search_ancestor_blocks_nested_markdown(self):
        html = '<section data-message-role="assistant"><div data-plugin-identifier="block_type:10025 | search_query_result_block.search_type:1">'
        html += '<div class="md-box-root" data-testid="message_text_content">搜索参考不是回答</div></div></section>'
        with self.assertRaisesRegex(ValueError, '未找到'):
            MAIN(encode(html), 'doubao')
        html += wrap('最终回答', 'doubao')
        self.assertEqual(MAIN(encode(html), 'doubao')['answer_raw_new'], '最终回答')

    def test_doubao_inline_tool_and_video_controls_are_removed(self):
        body = '<p>回答前段<a data-thinking-box-tool-call="true">资料标题</a>继续正文</p>'
        body += '<div data-testid="carousel-item">视频卡片标题</div><div data-testid="message_action_bar">复制按钮</div>'
        body += '<div data-testid="suggest_message_list">推荐追问</div><p>回答末尾</p>'
        result = MAIN(encode(wrap(body, 'doubao')), 'doubao')['answer_raw_new']
        self.assertEqual(result, '回答前段继续正文\n\n回答末尾')

    def test_doubao_does_not_depend_on_hashed_class_name(self):
        html = wrap('正文', 'doubao').replace('class="md-box-root"', 'class="container-newHash md-box-root"')
        self.assertEqual(MAIN(encode(html), ' DOUBAO ')['answer_raw_new'], '正文')

    def test_doubao_preserves_tables_and_restarts_independent_lists(self):
        body = '<h3>分组一</h3><ol><li>品牌甲</li><li>品牌乙</li></ol>'
        body += '<h3>分组二</h3><ol><li>冠珠</li><li>品牌丙</li></ol>'
        body += '<table><tr><th>品牌</th><th>优势</th></tr><tr><td>冠珠</td><td>款式多</td></tr></table>'
        result = MAIN(encode(wrap(body, 'doubao')), 'doubao')['answer_raw_new']
        self.assertIn('### 分组一\n\n1. 品牌甲\n2. 品牌乙', result)
        self.assertIn('### 分组二\n\n1. 冠珠\n2. 品牌丙', result)
        self.assertIn('| **冠珠** | 款式多 |', result)

    def test_doubao_encodings(self):
        for codec in ('plain', 'zlib', 'gzip', 'deflate'):
            with self.subTest(codec=codec):
                self.assertEqual(MAIN(encode(wrap('正文', 'doubao'), codec), 'doubao')['answer_raw_new'], '正文')

    def test_svg_void_tags_do_not_truncate_answer(self):
        body = '<p>正文前半段</p><svg><foreignObject><div>图内文字<br>第二行<img src="unused"></div></foreignObject></svg><p>正文后半段</p>'
        for platform in CLASSES:
            with self.subTest(platform=platform):
                parser = PARSER(platform)
                parser.feed(wrap(body, platform))
                parser.close()
                self.assertEqual(parser.result(), '正文前半段\n\n正文后半段')
                self.assertEqual(parser.ignore_depth, 0)

    def test_unclosed_ignored_child_is_unwound(self):
        html = wrap('<div class="ds-think-content"><span>思考</div><p>回答</p>')
        self.assertEqual(MAIN(encode(html), 'deepseek')['answer_raw_new'], '回答')

    def test_table_void_tags(self):
        body = '<table><tr><th>品牌</th><th>描述</th></tr><tr><td><strong>甲品牌</strong></td><td>前半<br>后半<img src="unused"></td></tr></table><p>表后正文</p>'
        result = MAIN(encode(wrap(body)), 'deepseek')['answer_raw_new']
        self.assertIn('| **甲品牌** | 前半 后半 |', result)
        self.assertTrue(result.endswith('表后正文'))

    def test_headings_and_lists(self):
        result = MAIN(encode(wrap('<h2>推荐</h2><ol><li>甲品牌</li><li>乙品牌</li></ol>')), 'deepseek')['answer_raw_new']
        self.assertEqual(result, '## 推荐\n\n1. 甲品牌\n2. 乙品牌')

    def test_encodings(self):
        for codec in ('plain', 'zlib', 'gzip', 'deflate'):
            with self.subTest(codec=codec):
                self.assertEqual(MAIN(encode(wrap('正文'), codec), 'deepseek')['answer_raw_new'], '正文')

    def test_empty_invalid_unknown_and_thinking_only(self):
        samples = ['', '%%%', encode('<body>普通网页</body>'), encode(wrap('')),
                   encode('<div class="ds-think-content"><div class="ds-assistant-message-main-content">只有思考</div></div>')]
        for sample in samples:
            with self.subTest(sample=sample[:30]):
                with self.assertRaises(ValueError):
                    MAIN(sample, 'deepseek')

    def test_zhipu_preview_controls_removed_but_source_preserved(self):
        body = '<div class="code-preview"><div class="toolbar">复制按钮</div><div class="preview-pane"><svg>重复图形</svg></div><pre class="code-pane"><span class="line-number">88</span><span class="line-content">flowchart TD</span></pre></div><p>后续正文</p>'
        result = MAIN(encode(wrap(body, 'zhipu')), 'zhipu')['answer_raw_new']
        self.assertIn('flowchart TD', result)
        self.assertIn('后续正文', result)
        for noise in ('复制按钮', '重复图形', '88'):
            self.assertNotIn(noise, result)

    def test_workflow_contract_and_no_old_answer_input(self):
        extractor = NODES['1766746558988']
        selectors = {item['variable']: item['value_selector'] for item in extractor['variables']}
        self.assertEqual(selectors, {'answer_html_b64': ['1766746558986', 'answer_html_b64'], 'model_id': ['1766746558986', 'model_id']})
        self.assertEqual(set(extractor['outputs']), {'answer_raw_new', 'parse_status', 'parse_error'})
        model_input = next(item for item in NODES['1766746558986']['variables'] if item['variable'] == 'model_id')
        self.assertTrue(model_input['required'])
        for node_id, data in NODES.items():
            if data['type'] == 'code':
                compile(data['code'], node_id, 'exec')
            for variable in data.get('variables', []):
                if isinstance(variable, dict):
                    self.assertNotEqual(variable.get('value_selector'), ['1766746558986', 'answer_raw'])
        self.assertNotIn('{{#1766746558986.answer_raw#}}', WORKFLOW_PATH.read_text())


if __name__ == '__main__':
    unittest.main()
