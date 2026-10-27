import copy
import json
import tempfile
import unittest
from pathlib import Path

from batch_runner import candidate_names, verify_identity, run_queue, BatchStopped
from batch_runner import MallNavigator
from unittest.mock import patch


class BatchRunnerTests(unittest.TestCase):
    def test_start_from_selected_id_keeps_prefix_saved_results_and_order(self):
        with tempfile.TemporaryDirectory() as temp:
            roster = {'items': [
                {'task_id': 'a', 'name': '同名商场', 'status': '待采集'},
                {'task_id': 'b', 'name': '同名商场', 'status': '待采集'},
                {'task_id': 'c', 'name': 'C', 'status': '已保存（待复核）', 'result': {'folder': 'old/C'}},
                {'task_id': 'd', 'name': 'D', 'status': '待确认', 'last_error': '核对地址'},
                {'task_id': 'e', 'name': 'E', 'status': '待采集'}]}
            original = copy.deepcopy(roster)
            called, messages = [], []
            def capture(item):
                called.append(item['task_id'])
                return {'folder': 'new/' + item['task_id']}
            checkpoint = Path(temp) / 'queue.json'
            result = run_queue(roster, checkpoint, capture, lambda: False,
                               messages.append, start_task_id='b')
            self.assertEqual(called, ['b', 'e'])
            for index in (0, 2, 3):
                self.assertEqual(roster['items'][index], original['items'][index])
            self.assertTrue(messages[0].startswith('2/5 '))
            self.assertEqual(json.loads(checkpoint.read_text(encoding='utf-8')), roster)
            self.assertEqual(result['pending'], 1)

    def test_start_from_missing_id_fails_before_capture_or_checkpoint_write(self):
        with tempfile.TemporaryDirectory() as temp:
            roster = {'items': [{'task_id': 'a', 'name': 'A', 'status': '待采集'}]}
            checkpoint = Path(temp) / 'queue.json'
            checkpoint.write_text('original', encoding='utf-8')
            called = []
            with self.assertRaises(ValueError):
                run_queue(roster, checkpoint, lambda item: called.append(item),
                          lambda: False, start_task_id='missing')
            self.assertEqual(called, [])
            self.assertEqual(checkpoint.read_text(encoding='utf-8'), 'original')
            self.assertEqual(roster['items'][0]['status'], '待采集')

    def test_single_from_selected_preserves_full_roster_and_can_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            roster = {'items': [dict(task_id=name, name=name, status='待采集') for name in 'ABCD']}
            checkpoint = Path(temp) / 'queue.json'
            called = []
            def capture(item):
                called.append(item['name'])
                return {'folder': item['name']}
            run_queue(roster, checkpoint, capture, lambda: False, start_task_id='B', single=True)
            self.assertEqual(called, ['B'])
            self.assertEqual(len(json.loads(checkpoint.read_text(encoding='utf-8'))['items']), 4)
            run_queue(roster, checkpoint, capture, lambda: False, start_task_id='B')
            self.assertEqual(called, ['B', 'C', 'D'])
            self.assertEqual(roster['items'][0]['status'], '待采集')

    def test_click_that_does_not_navigate_is_retried_and_waits_for_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            state = {'clicks': 0, 'inspects': 0}
            def transport(handle, mode, **kwargs):
                if mode == 'click':
                    state['clicks'] += 1
                if mode == 'inspect':
                    state['inspects'] += 1
                    return {'documents': [{'text': '测试商场\n商场服务' if state['clicks'] > 1 else '筛选\n全部分类\n测试商场\n商场'}]}
                return {'ok': True}
            with patch('batch_runner.time.sleep'):
                result = MallNavigator(1, temp, transport=transport).click_mall_result('测试商场')
            self.assertIn('商场服务', result)
            self.assertEqual(state['clicks'], 2)
            self.assertGreater(state['inspects'], 2)

    def test_click_retry_is_bounded_and_never_repeats_after_focus_loss(self):
        from batch_runner import NavigationError
        for error, expected, count in [('当前可见区域未找到可点击文字', ValueError, 3),
                                       ('目标窗口失去焦点，已停止自动操作', BatchStopped, 1)]:
            with self.subTest(error=error), tempfile.TemporaryDirectory() as temp:
                calls = []
                def transport(handle, mode, **kwargs):
                    calls.append(mode)
                    if mode == 'click':
                        raise RuntimeError(error)
                    return {'documents': [{'text': '筛选\n全部分类\n测试商场\n商场'}]}
                with patch('batch_runner.time.sleep'), self.assertRaises(expected):
                    MallNavigator(1, temp, transport=transport).click_mall_result('测试商场')
                self.assertEqual(calls.count('click'), count)

    def test_click_retry_stops_when_unexpected_page_opens(self):
        with tempfile.TemporaryDirectory() as temp:
            calls = []
            def transport(handle, mode, **kwargs):
                calls.append(mode)
                return {'documents': [{'text': '不相关商户\n写评价\n收藏'}]} if mode == 'inspect' else {'ok': True}
            with patch('batch_runner.time.sleep'), self.assertRaisesRegex(ValueError, '停止重试'):
                MallNavigator(1, temp, transport=transport).click_mall_result('测试商场')
            self.assertEqual(calls.count('click'), 1)

    def test_unique_exact_result_can_open_list_when_home_omits_district(self):
        with tempfile.TemporaryDirectory() as temp:
            state = {'list': False}
            home = 'COSMO\n大业路\n商场\n商场服务\n10:00-22:00\n大业路6号\n全部\n(86)\n查看全部86家门店  '
            def transport(handle, mode, **kwargs):
                if mode == 'click' and kwargs.get('text') == '查看全部86家门店':
                    state['list'] = True
                if mode == 'inspect':
                    return {'documents': [{'text': '输入商户名、地点、找优惠\n全部楼层\n全部分类' if state['list'] else home}]}
                return {'ok': True}
            navigator = MallNavigator(1, temp, transport=transport)
            with patch.object(navigator, 'search', return_value='COSMO 锦江区\n全部分类\n筛选\nCOSMO\n4.9\n商场\n大业路'), patch('batch_runner.time.sleep'):
                result = navigator.open_mall({'name': 'COSMO', 'district': '锦江区'})
            self.assertTrue(state['list'])
            self.assertEqual(result['geography_status'], 'unresolved')
            self.assertEqual(result['expected_store_count'], 86)

    def test_explicit_address_conflict_is_not_relaxed_by_exact_result(self):
        text = 'COSMO\n商场服务\n大业路6号\n全部\n(86)'
        self.assertFalse(verify_identity(text, {'name': 'COSMO', 'district': '锦江区', 'address': '其他路99号'}, matched_candidate='COSMO')['verified'])

    def test_navigation_failure_pauses_before_searching_next_mall(self):
        from batch_runner import NavigationError
        with tempfile.TemporaryDirectory() as temp:
            roster = {'items': [{'name': 'A', 'status': '待采集'}, {'name': 'B', 'status': '待采集'}]}
            called = []
            def capture(item):
                called.append(item['name'])
                raise NavigationError('等待全部商户列表超时')
            result = run_queue(roster, Path(temp) / 'queue.json', capture, lambda: False)
            self.assertTrue(result['stopped'])
            self.assertEqual(called, ['A'])
            self.assertEqual(roster['items'][0]['status'], '待确认')
            self.assertEqual(roster['items'][1]['status'], '待采集')

    def test_candidate_is_mall_result_not_a_tenant_or_query_header(self):
        text = '群光广场\n商户\n全城\n全部分类\n筛选\n\ufffc\n星巴克(群光广场店)\n★\n4.3\n咖啡\n锦江区\n\ufffc\n群光广场\n★\n4.5\n12条\n商场\n春熙路\n锦江区购物榜第1名\n'
        self.assertEqual(candidate_names(text, {'name': '群光广场'}), ['群光广场'])

    def test_same_name_multiple_malls_remains_ambiguous(self):
        text = '筛选\n\ufffc\n万达广场(金牛店)\n4.5\n商场\n金牛区\n\ufffc\n万达广场(锦江店)\n4.3\n商场\n锦江区\n'
        self.assertEqual(len(candidate_names(text, {'name': '万达广场'})), 2)

    def test_identity_ignores_district_in_tenant_reviews(self):
        item = {'name': '群光广场', 'district': '锦江区'}
        self.assertFalse(verify_identity('群光广场\n商场服务\n地址未知\n全部\n(10)\n锦江区客户评价', item)['verified'])
        self.assertTrue(verify_identity('群光广场\n商场服务\n锦江区春熙路1号\n全部\n(10)', item)['verified'])

    def test_queue_records_ambiguous_and_resumes_without_overwriting_success(self):
        with tempfile.TemporaryDirectory() as temp:
            checkpoint = Path(temp) / 'queue.json'
            roster = {'items': [{'task_id': 'a', 'name': 'A', 'status': '待采集'}, {'task_id': 'b', 'name': 'B', 'status': '待采集'}]}
            called = []
            def capture(item):
                called.append(item['name'])
                if item['name'] == 'B':
                    raise ValueError('搜索结果不唯一，待确认')
                return {'folder': 'saved/A', 'bottom_confirmed': True}
            run_queue(roster, checkpoint, capture, lambda: False)
            self.assertEqual([i['status'] for i in roster['items']], ['已保存（待复核）', '待确认'])
            run_queue(roster, checkpoint, capture, lambda: False)
            self.assertEqual(called, ['A', 'B'])
            self.assertTrue(checkpoint.exists())

    def test_user_stop_leaves_task_pending_and_stops_next_target(self):
        with tempfile.TemporaryDirectory() as temp:
            roster = {'items': [{'name': 'A', 'status': '待采集'}, {'name': 'B', 'status': '待采集'}]}
            def capture(item):
                raise BatchStopped('窗口失去焦点')
            result = run_queue(roster, Path(temp) / 'queue.json', capture, lambda: False)
            self.assertTrue(result['stopped'])
            self.assertEqual(roster['items'][0]['status'], '待采集')
            self.assertEqual(roster['items'][1]['status'], '待采集')

    def test_full_controller_search_identity_then_list_with_expected_actions(self):
        with tempfile.TemporaryDirectory() as temp:
            state = {'page': 'home', 'query': ''}
            calls = []
            mall_clicks = {'count': 0}
            def transport(handle, mode, **kwargs):
                calls.append((mode, kwargs))
                if mode == 'type':
                    state['query'] = kwargs['text']
                elif mode == 'click' and kwargs.get('text') == '搜索':
                    state['page'] = 'entry'
                elif mode == 'key':
                    state['page'] = 'results'
                elif mode == 'click' and kwargs.get('after') == '筛选':
                    mall_clicks['count'] += 1
                    if mall_clicks['count'] == 1:
                        raise RuntimeError('当前可见区域未找到可点击文字：测试商场')
                    state['page'] = 'identity'
                elif mode == 'click' and kwargs['text'] == '查看全部2家门店':
                    state['page'] = 'list'
                if mode == 'inspect':
                    text = {'home': '搜索\n首页', 'entry': state['query'] + '\n取消\n最近搜索', 'results': state['query'] + '\n商户\n全部分类\n筛选\n测试商场\n★\n4.5\n商场\n锦江区',
                            'identity': '测试商场\n商场服务\n锦江区春熙路1号\n全部\n(2)\n查看全部2家门店',
                            'list': '输入商户名、地点、找优惠\n全部楼层\n全部分类'}[state['page']]
                    return {'documents': [{'text': text}]}
                return {'ok': True}
            navigator = MallNavigator(1, temp, transport=transport)
            with patch('batch_runner.time.sleep'):
                result = navigator.open_mall({'name': '测试商场', 'district': '锦江区'})
            self.assertTrue(result['verified'])
            self.assertEqual(state['page'], 'list')
            self.assertIn(('type', {'text': '测试商场 锦江区'}), calls)
            self.assertIn(('click', {'text': '测试商场', 'after': '筛选'}), calls)
            self.assertEqual(mall_clicks['count'], 2)
            self.assertIn(('click', {'text': '查看全部2家门店'}), calls)

    def test_access_challenge_halts_instead_of_advancing_queue(self):
        with tempfile.TemporaryDirectory() as temp:
            navigator = MallNavigator(1, temp, transport=lambda *a, **k: {'documents': [{'text': '请完成验证'}]})
            with self.assertRaises(BatchStopped):
                navigator.inspect()

    def test_search_opens_existing_query_text_instead_of_fractional_coordinates(self):
        with tempfile.TemporaryDirectory() as temp:
            state = {'page': 'results', 'query': '新城市购物广场', 'typed': False}
            calls = []
            def transport(handle, mode, **kwargs):
                calls.append((mode, kwargs))
                if mode == 'point':
                    return {'ok': True}
                if mode == 'click' and kwargs.get('text') == '新城市购物广场':
                    state['page'] = 'entry'
                elif mode == 'type' and state['page'] == 'entry':
                    state['query'] = kwargs['text']
                    state['typed'] = True
                elif mode == 'key' and state['typed']:
                    state['page'] = 'results'
                elif mode == 'click':
                    raise ValueError('Visible text not found')
                if mode == 'inspect':
                    text = (state['query'] + '\n商户\n全部分类\n筛选\n测试商场\n商场') if state['page'] == 'results' else state['query'] + '\n取消\n搜索历史'
                    return {'documents': [{'text': text}]}
                return {'ok': True}
            navigator = MallNavigator(1, temp, transport=transport)
            with patch('batch_runner.time.sleep'):
                text = navigator.search('壹购潮流广场 锦江区')
            self.assertIn('壹购潮流广场 锦江区', text)
            self.assertNotIn('point', [mode for mode, _ in calls])
            self.assertIn(('click', {'text': '新城市购物广场'}), calls)

    def test_search_resumes_from_editor_with_cancel_label(self):
        with tempfile.TemporaryDirectory() as temp:
            state = {'query': '上一次商场', 'page': 'entry'}
            calls = []
            def transport(handle, mode, **kwargs):
                calls.append((mode, kwargs))
                if mode == 'click' and kwargs.get('text') != state['query']:
                    raise ValueError('Not a search field')
                if mode == 'type':
                    state['query'] = kwargs['text']
                if mode == 'key':
                    state['page'] = 'results'
                if mode == 'inspect':
                    tail = '\n取消\n最近搜索' if state['page'] == 'entry' else '\n商户\n全部分类\n筛选'
                    return {'documents': [{'text': state['query'] + tail}]}
                return {'ok': True}
            with patch('batch_runner.time.sleep'):
                text = MallNavigator(1, temp, transport=transport).search('目标商场 锦江区')
            self.assertIn('目标商场 锦江区', text)
            self.assertNotIn('back', [mode for mode, _ in calls])

    def test_search_does_not_type_when_search_field_did_not_open(self):
        with tempfile.TemporaryDirectory() as temp:
            calls = []
            def transport(handle, mode, **kwargs):
                calls.append(mode)
                return {'documents': [{'text': '旧商场\n商户\n全部分类\n筛选'}]} if mode == 'inspect' else {'ok': True}
            with patch('batch_runner.time.sleep'), self.assertRaisesRegex(ValueError, '搜索输入页'):
                MallNavigator(1, temp, transport=transport).search('新商场')
            self.assertNotIn('type', calls)


if __name__ == '__main__':
    unittest.main()
