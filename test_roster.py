import tempfile
import unittest
from pathlib import Path

from excel_import import write_xlsx
from roster import load_roster


class RosterTests(unittest.TestCase):
    def test_only_exact_commerce_source_is_used_with_original_row_numbers(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'source.xlsx'
            write_xlsx(path, [('成都市综合体原始清单', [
                ['来源', '行政区域', '项目名称', '审核判定'],
                ['新潮', '青羊区', 'A', '商业综合体'],
                ['商务局', '锦江区', 'B', '待核'],
                [' 商务局 ', '成华区', 'C', '非综合体'],
                ['商务局补充', '锦江区', 'D', '商业综合体'],
            ], [20] * 4)])
            result = load_roster(path)
            self.assertEqual([r['name'] for r in result['items']], ['B', 'C'])
            self.assertEqual([r['source_row'] for r in result['items']], [3, 4])
            self.assertEqual(result['items'][1]['assessment'], '非综合体')
            self.assertEqual(result['total_rows'], 4)

    def test_missing_required_headers_fails_instead_of_using_other_sheet(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'source.xlsx'
            write_xlsx(path, [('成都市综合体原始清单', [['项目名称'], ['A']], [20])])
            with self.assertRaises(ValueError):
                load_roster(path)

    def test_search_query_contains_name_and_district_with_alias(self):
        from roster import search_queries
        item = {'name': '王府井', 'district': '锦江区', 'alias': '王府井百货'}
        self.assertEqual(search_queries(item), ['王府井 锦江区', '王府井百货 锦江区'])

    def test_generic_csv_accepts_user_list_and_filters_source_when_present(self):
        from roster import load_task_list
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'list.csv'
            path.write_text('商场名称,所在区,地址,来源\nA,锦江区,1号,商务局\nB,青羊区,2号,新潮\n', encoding='utf-8-sig')
            result = load_task_list(path)
            self.assertEqual([i['name'] for i in result['items']], ['A'])
            self.assertEqual(result['items'][0]['address'], '1号')

    def test_generic_csv_without_source_keeps_user_provided_list(self):
        from roster import load_task_list
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'list.csv'
            path.write_text('商场名称,所在区\nA,锦江区\nB,青羊区\n', encoding='utf-8-sig')
            self.assertEqual(load_task_list(path)['count'], 2)

    def test_exported_roster_reimport_keeps_source_row_and_task_identity(self):
        from roster import load_task_list
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'list.csv'
            path.write_text('任务编号,原表行号,商场名称,来源\ncommerce-row-53,53,A,商务局\n', encoding='utf-8-sig')
            item = load_task_list(path)['items'][0]
            self.assertEqual(item['task_id'], 'commerce-row-53')
            self.assertEqual(item['source_row'], 53)


if __name__ == '__main__':
    unittest.main()
