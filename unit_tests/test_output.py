import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import numpy as np
import tcurve as tc


class PlainOutputTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix='tcurve-output-')
        self.addCleanup(self.work.cleanup)
        self.output = io.StringIO()
        self.redirect = redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)

    def dash(self, **kwargs):
        return tc.Dash(log_dir=self.work.name, metrics={'loss': ['.2f', tc.RAW]}, **kwargs)

    def test_each_epoch_prints_once_without_terminal_building(self):
        dash = self.dash()
        dash.resources_active = True
        dash.resource_monitor = mock.Mock()
        with mock.patch.object(dash, '_build_frame_state', side_effect=AssertionError('terminal frame built')):
            for epoch in range(15):
                dash({'loss': 2.0}, epoch, 0, 2)
                self.assertEqual(len(self.output.getvalue().splitlines()), epoch)
                dash({'loss': 4.0}, epoch, 1, 2)
            dash.finalize(review=False)
            dash.finalize(review=False)
        lines = self.output.getvalue().splitlines()
        self.assertEqual(len(lines), 15)
        self.assertTrue(all('3.00' in line for line in lines))
        self.assertNotIn('\033', self.output.getvalue())
        self.assertNotIn('\r', self.output.getvalue())
        dash.resource_monitor.snapshot.assert_not_called()
        self.assertEqual(len(dash.gauge_epoch[('ITER', 'loss')]), 15)

    def test_partial_summary_is_immediate_and_not_duplicated(self):
        dash = self.dash()
        dash({'loss': 2.0}, 0, 0, 10, stage='TRAIN')
        dash({'loss': 4.0}, 0, 1, 10, stage='TRAIN')
        self.assertEqual(self.output.getvalue(), '')
        dash.end_epoch(stage='TRAIN')
        dash.end_epoch(stage='TRAIN')
        dash.finalize(review=False)
        self.assertEqual(len(self.output.getvalue().splitlines()), 1)
        self.assertIn('partial 2/10', self.output.getvalue())
        self.assertIn('3.00', self.output.getvalue())

    def test_unknown_total_prints_latest_progress_only_at_finalize(self):
        dash = self.dash()
        dash({'loss': 1.0}, 0, 0, None, interv=0, plot=True)
        dash({'loss': 4.0}, 0, 1, None, interv=0, plot=True)
        self.assertEqual(self.output.getvalue(), '')
        dash.finalize(review=False)
        dash.finalize(review=False)
        self.assertEqual(len(self.output.getvalue().splitlines()), 1)
        self.assertIn('2 Miles', self.output.getvalue())
        self.assertIn('4.00', self.output.getvalue())
        self.assertNotIn('\033', self.output.getvalue())
        self.assertNotIn('\r', self.output.getvalue())

    def test_finalization_closes_multiple_stages(self):
        dash = self.dash()
        dash({'loss': 2.0}, 0, 0, 10, stage='TRAIN')
        dash({'loss': 8.0}, 0, 0, 10, stage='VAL')
        dash.finalize(review=False)
        lines = self.output.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn('TRAIN partial', lines[0])
        self.assertIn('VAL partial', lines[1])

    def test_summary_is_not_width_clipped_and_removes_controls(self):
        stage = 'long-' + 's' * 500 + '\033[31m\r\n'
        dash = self.dash()
        dash({'loss': 2.0}, 0, 0, 1, stage=stage)
        text = self.output.getvalue()
        self.assertIn('s' * 500, text)
        self.assertEqual(len(text.splitlines()), 1)
        self.assertNotRegex(text.rstrip('\n'), r'[\x00-\x1f\x7f-\x9f]')

    def test_image_callback_runs_without_character_preview(self):
        callback = mock.Mock(return_value=True)
        dash = tc.Dash(log_dir=self.work.name, metrics={'img': [callback, tc.IMAGE]})
        dash({'img': np.ones((4, 4), dtype=np.float32)}, 0, 0, 10)
        dash.finalize(review=False)
        self.assertEqual(callback.call_count, 2)
        self.assertEqual(dash.char_image, '')
        self.assertEqual(dash.image_row, 0)

    def test_wrapper_outputs_one_completion_with_latest_value(self):
        self.assertEqual(list(tc.Dash(range(3), metrics={'loss': ['.2f', tc.RAW]})), [0, 1, 2])
        self.assertEqual(len(self.output.getvalue().splitlines()), 1)
        self.assertIn('2.00', self.output.getvalue())

    def test_custom_completion_is_sanitized_without_extra_callback_calls(self):
        callback = mock.Mock(return_value='result\033[31m\nnext\rline')
        dash = tc.Dash(log_dir=self.work.name, metrics={'value': [callback, tc.CUSTOM]})
        dash({'value': 1}, 0, 0, 1)
        dash.finalize(review=False)
        self.assertEqual(callback.call_count, 2)
        self.assertEqual(len(self.output.getvalue().splitlines()), 1)
        self.assertIn('result next line', self.output.getvalue())
        self.assertNotIn('\033', self.output.getvalue())


class HeadlessExportTests(unittest.TestCase):
    def test_exports_with_gui_backend_configured_without_changing_it(self):
        with tempfile.TemporaryDirectory(prefix='tcurve-agg-') as work:
            script = '''
import os, sys
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from unittest import mock
import numpy as np
from PIL import Image
import tcurve as tc
from tcurve.utils import plot_in_one
dash = tc.Dash(log_dir=sys.argv[1], metrics={'loss': ['.2f', tc.RAW]})
dash({'loss': 1.0}, 0, 0, 2)
dash({'loss': 2.0}, 0, 1, 2)
with mock.patch.object(plt, 'figure', side_effect=AssertionError('GUI figure created')):
    dash.plot_curves(subdir='plots')
    sources = []
    for index in range(2):
        path = os.path.join(sys.argv[1], str(index) + '.csv')
        np.savetxt(path, [[0, index], [1, index + 1]], delimiter=',')
        sources.append(path)
    plot_in_one(['a', 'b'], sources, os.path.join(sys.argv[1], 'merged.png'))
assert matplotlib.get_backend().lower() == 'tkagg'
paths = [os.path.join(sys.argv[1], 'plots', name) for name in os.listdir(os.path.join(sys.argv[1], 'plots'))]
paths.append(os.path.join(sys.argv[1], 'merged.png'))
assert len(paths) == 3
for path in paths:
    with Image.open(path) as image:
        pixels = np.asarray(image)
        assert image.width > 100 and image.height > 100 and pixels.std() > 1
'''
            env = dict(os.environ)
            env.pop('DISPLAY', None)
            env.pop('WAYLAND_DISPLAY', None)
            result = subprocess.run([sys.executable, '-c', script, work], env=env,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_export_preserves_callers_existing_figures(self):
        with tempfile.TemporaryDirectory(prefix='tcurve-figures-') as work:
            script = '''
import sys
import matplotlib
matplotlib.use('svg')
import matplotlib.pyplot as plt
import tcurve as tc
existing = plt.figure()
existing.add_subplot(111).plot([1, 2])
numbers = plt.get_fignums()
dash = tc.Dash(log_dir=sys.argv[1], metrics={'loss': ['.2f', tc.RAW]})
dash({'loss': 1.0}, 0, 0, 1)
dash.plot_curves(subdir='plots')
assert matplotlib.get_backend().lower() == 'svg'
assert plt.get_fignums() == numbers
assert existing.axes[0].lines[0].get_ydata().tolist() == [1, 2]
plt.close(existing)
'''
            result = subprocess.run([sys.executable, '-c', script, work], capture_output=True,
                                    text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
