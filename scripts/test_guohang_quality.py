"""Run with: python3 scripts/test_guohang_quality.py (Ruby supplies YAML parsing)."""
import copy
import json
import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
YAML_PATH = REPO / 'workflows/guohangshengwen.yml'
WORKFLOW = json.loads(subprocess.check_output(
    ['ruby', '-ryaml', '-rjson', '-e', 'puts JSON.generate(YAML.load_file(ARGV[0]))', str(YAML_PATH)],
    text=True,
))
GRAPH = WORKFLOW['workflow']['graph']
NODES = {str(n['id']): n for n in GRAPH['nodes']}


def node_main(node_id):
    namespace = {}
    exec(compile(NODES[node_id]['data']['code'], node_id, 'exec'), namespace)
    return namespace['main']


def article(length=3000, extra='', mode='category'):
    # Exact visible length, including headings; synthetic text is for code tests only.
    sections = ''.join('<h2>规则说明</h2>' for _ in range(5))
    content = sections + '<p>' + '文' * (length - 20 - len(extra)) + extra + '</p>'
    return {'title': '国航凤凰知音会员规则与服务使用条件详细说明',
            'content': content, 'description': '会员服务规则说明', 'tags': ['国航', '会员'],
            'self_review': '测试', '_keyword_mode': mode}


class QualityRegression(unittest.TestCase):
    def test_workflow_shape_and_code(self):
        self.assertEqual(len(NODES), len(GRAPH['nodes']))
        self.assertEqual(len({e['id'] for e in GRAPH['edges']}), len(GRAPH['edges']))
        for node_id, node in NODES.items():
            data = node['data']
            if data['type'] == 'code':
                self.assertEqual(data['code_language'], 'python3')
                compile(data['code'], node_id, 'exec')
        for edge in GRAPH['edges']:
            self.assertIn(edge['source'], NODES)
            self.assertIn(edge['target'], NODES)
            for endpoint in ('source', 'target'):
                self.assertEqual(edge['data'][endpoint + 'Type'], NODES[edge[endpoint]]['data']['type'])
            if edge['data'].get('isInIteration'):
                for endpoint in ('source', 'target'):
                    self.assertEqual(NODES[edge[endpoint]]['parentId'], edge['data']['iteration_id'])

    def test_all_nodes_reachable_and_end_reachable(self):
        for parent in (None, '1776938309919', '1777400000006'):
            group = {key for key, n in NODES.items() if (n.get('parentId') or None) == parent}
            edges = [(e['source'], e['target']) for e in GRAPH['edges'] if e['source'] in group and e['target'] in group]
            start = NODES[parent]['data']['start_node_id'] if parent else '1776153503356'
            end = NODES[parent]['data']['output_selector'][0] if parent else '1776946313229'
            def walk(seed, reverse=False):
                reached = {seed}
                while True:
                    expanded = reached | {a if reverse else b for a, b in edges if (b if reverse else a) in reached}
                    if reached == expanded:
                        return reached
                    reached = expanded
            self.assertEqual(walk(start), group)
            self.assertEqual(walk(end, reverse=True), group)

    def test_shared_checker_is_identical_in_all_stages(self):
        source = (REPO / 'scripts/guohang_quality.py').read_text()
        for key in ('1792000000001', '17769383496072', '1779793980326',
                    '17769383496069', '1780921365192', '1786200000001'):
            self.assertTrue(NODES[key]['data']['code'].startswith(source), key)

    def test_original_failure_detected_before_repair(self):
        for key in ('1792000000001', '17769383496072'):
            check = node_main(key)
            result = check(json.dumps(article(4412, '终身享受服务。'), ensure_ascii=False))
            self.assertEqual(result['content_len'], 4412)
            self.assertEqual(result['has_issues'], 1)
            self.assertIn('终身享受服务', result['issues'])
            self.assertIn('4412', result['issues'])
            second = check(article(extra='唯一的服务选择，终身权益。'))
            self.assertIn('唯一', second['issues'])
            self.assertIn('终身', second['issues'])

    def test_shared_length_boundaries(self):
        for key in ('1792000000001', '17769383496072'):
            for length, bad in ((2499, 1), (2500, 0), (4200, 0), (4201, 1)):
                with self.subTest(node=key, length=length):
                    result = node_main(key)(article(length))
                    self.assertEqual(result['has_issues'], bad)
                    self.assertEqual(result['content_len'], length)

    def test_no_silent_original_fallback(self):
        for key in ('1779793980326', '17769383496069'):
            good = article()
            bad = article(extra='终身权益')
            with self.assertRaisesRegex(ValueError, '终身'):
                node_main(key)(good, bad)
            with self.assertRaises(ValueError):
                node_main(key)(bad, '{"content":"truncated')
            repaired = node_main(key)(bad, good)['structured_output']
            self.assertEqual(repaired['content'], good['content'])

    def test_no_fact_or_name_rewriting(self):
        original = article(extra='终身白金卡会员的办理条件。')
        snapshot = copy.deepcopy(original)
        result = node_main('17769383496072')(original)
        self.assertIn('终身白金卡会员', result['issues'])
        self.assertEqual(original, snapshot)
        with self.assertRaises(ValueError):
            node_main('1780921365192')(original)

    def test_brand_competitor_and_category_background(self):
        sample = article(extra='中国东方航空、中国南方航空。')
        self.assertEqual(node_main('17769383496072')(sample)['has_issues'], 1)
        self.assertEqual(node_main('1792000000001')(sample)['has_issues'], 0)

    def test_html_and_json_failures(self):
        broken = article()
        broken['content'] = broken['content'][:-4]
        self.assertIn('未闭合', node_main('1792000000001')(broken)['issues'])
        self.assertIn('JSON', node_main('1792000000001')('{"title":"截断')['issues'])
        fragmented = article()
        fragmented['content'] += '<p>终<strong>身</strong>权益</p>'
        self.assertIn('终身', node_main('1792000000001')(fragmented)['issues'])

    def test_n8_pre_blocks_formatting_damage_without_rewriting(self):
        good = article()
        self.assertEqual(node_main('1777100000001')([good])['cleaned_articles'][0]['_structural_validation'], 'passed')
        broken = copy.deepcopy(good)
        broken['content'] = broken['content'].replace('</p>', '[官网](https://example.com)</p>', 1)
        with self.assertRaisesRegex(ValueError, 'Markdown链接'):
            node_main('1777100000001')([broken])

    def test_repair_prompt_receives_measurements_and_context(self):
        for repair, check in (('1779970859223', '1792000000001'), ('17769383496066', '17769383496072')):
            prompt = '\n'.join(p['text'] for p in NODES[repair]['data']['prompt_template'])
            self.assertIn('{{#' + check + '.content_len#}}', prompt)
            self.assertIn('{{#' + check + '.issues#}}', prompt)
            self.assertIn('超过4200字', prompt)
            self.assertIn('不得机械删词', prompt)

    def test_final_gate_and_five_field_contract(self):
        good = [article(mode='category'), article(mode='brand')]
        result = node_main('1786200000001')(good)
        self.assertEqual(len(result['validated_articles']), 2)
        for source, final in zip(good, result['validated_articles']):
            self.assertEqual(final['content'], source['content'])
        with self.assertRaisesRegex(ValueError, '第1篇.*4412.*第2篇'):
            node_main('1786200000001')([article(4412, '终身权益'), article(extra='唯一终身权益')])
        self.assertEqual([o['variable'] for o in NODES['1776946313229']['data']['outputs']],
                         ['article_titles', 'quality_scores', 'generated_articles_list', 'article_tags', 'evidence'])


if __name__ == '__main__':
    unittest.main()
