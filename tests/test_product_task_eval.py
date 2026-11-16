"""Project routing regressions; synthetic reports are not business evidence."""
import json
import tempfile
import unittest
from pathlib import Path

from eval.harness import EVALS, PROJECT_CASES
from workbench.task_store import TaskStore
from workbench.workflow import _blocking_cases_for_workspace, run_task


class ProductTaskEvalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'candidate'
        self.workspace.mkdir()

    def product(self):
        (self.workspace / 'flowerp').mkdir()
        (self.workspace / 'flowerp/server.py').write_text('')
        (self.workspace / 'eval').mkdir()
        (self.workspace / 'eval/__init__.py').write_text('')
        allowed = [name for name, level, _ in EVALS
                   if level == 'blocking' and name in PROJECT_CASES]
        # Reject controller-only names just as the independent product does.
        (self.workspace / 'eval/harness.py').write_text('''
import argparse, json
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--suite')
p.add_argument('--case', action='append', choices=ALLOWED)
p.add_argument('--report-path')
a = p.parse_args()
failed = Path('fail').exists()
results = [dict(name=n, level='blocking', passed=not (failed and i == 0))
           for i, n in enumerate(a.case)]
summary = dict(total=len(results), passed=len(results)-int(failed),
               blocking_failed=int(failed), observing_failed=0,
               decision='block' if failed else 'pass')
Path(a.report_path).write_text(json.dumps(dict(schema_version='1.0',
    suite=a.suite, requested_cases=a.case, summary=summary, results=results)))
raise SystemExit(int(failed))
'''.replace('choices=ALLOWED', 'choices=' + repr(allowed)), encoding='utf-8')

    def test_product_gets_all_controller_registered_product_checks(self):
        self.product()
        self.assertEqual(tuple(n for n, level, _ in EVALS
                               if level == 'blocking' and n in PROJECT_CASES),
                         _blocking_cases_for_workspace(self.workspace))

    def test_controller_and_combined_candidates_keep_full_scope(self):
        all_cases = tuple(n for n, level, _ in EVALS if level == 'blocking')
        self.assertEqual(all_cases, _blocking_cases_for_workspace(self.workspace))
        self.product()
        (self.workspace / 'workbench').mkdir()
        self.assertEqual(all_cases, _blocking_cases_for_workspace(self.workspace))

    def test_incomplete_combined_snapshot_does_not_downgrade_checks(self):
        self.product()
        (self.workspace / '.course').mkdir()
        (self.workspace / '.course/product-source.json').write_text('{}')
        self.assertEqual(tuple(n for n, level, _ in EVALS if level == 'blocking'),
                         _blocking_cases_for_workspace(self.workspace))

    def test_real_subprocess_preserves_red_and_stops_green_at_review(self):
        self.product()
        runtime = self.root / 'runtime'
        store = TaskStore(runtime / 'workbench.db')
        spec = runtime / 'SPEC.md'
        spec.write_text('\n'.join('## ' + heading + '\nfixture' for heading in
            ('来源', '目标', '非目标', '约束', '验收用例', '完成定义')), encoding='utf-8')
        task = store.create_v0('synthetic project routing', spec_path=str(spec),
                              actor='test', workspace_path=str(self.workspace), execution_mode='verify')
        (self.workspace / 'fail').write_text('')
        red = run_task(store, task['id'])
        self.assertEqual('rework', red['status'])
        self.assertEqual(1, red['result']['runner']['process_returncode'])
        old_path = runtime / red['result']['report_path']
        old_bytes = old_path.read_bytes()
        (self.workspace / 'fail').unlink()
        green = run_task(store, task['id'])
        self.assertEqual('review', green['status'])
        self.assertEqual(0, green['result']['runner']['process_returncode'])
        self.assertEqual(old_bytes, old_path.read_bytes())
        self.assertEqual(set(PROJECT_CASES),
                         {item['name'] for item in green['result']['results']})
        self.assertIsNone(green['reviewed_by'])


if __name__ == '__main__':
    unittest.main()
