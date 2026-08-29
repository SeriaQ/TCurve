import io
import numpy as np
import os
import tempfile
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import tcurve as tc
import tcurve.dash as dash_module
from tcurve.resources import ResourceMonitor
from tcurve.utils import curve2str


warnings.filterwarnings('ignore', category=DeprecationWarning)


class QuietOutputMixin:
    def setUp(self):
        self._stdout = dash_module.stdout
        self._stdout_buffer = io.StringIO()
        self._stderr_buffer = io.StringIO()
        self._redirect_stdout = redirect_stdout(self._stdout_buffer)
        self._redirect_stderr = redirect_stderr(self._stderr_buffer)
        self._redirect_stdout.__enter__()
        self._redirect_stderr.__enter__()
        dash_module.stdout = self._stdout_buffer

    def tearDown(self):
        dash_module.stdout = self._stdout
        self._redirect_stderr.__exit__(None, None, None)
        self._redirect_stdout.__exit__(None, None, None)


class DashWrapperTests(unittest.TestCase):
    def test_plain_wrapper_progress_only(self):
        self.assertEqual(list(tc.Dash(range(3), show=False)), [0, 1, 2])

    def test_single_metric_scalar_auto_mapping(self):
        self.assertEqual(
            list(tc.Dash(range(3), metrics={'n': ['d', tc.RAW]}, show=False)),
            [0, 1, 2],
        )

    def test_single_metric_tuple_requires_entry_fn(self):
        with self.assertRaises(TypeError):
            list(tc.Dash(enumerate(range(2)), metrics={'n': ['d', tc.RAW]}, show=False))

    def test_multi_metric_tuple_auto_mapping(self):
        items = [(1, 0.1), (2, 0.2)]
        self.assertEqual(
            list(tc.Dash(items, metrics={'step': ['d', tc.RAW], 'acc': ['.1f', tc.PERCENT]}, show=False)),
            items,
        )

    def test_entry_fn_uses_index_first_signature(self):
        items = list(
            tc.Dash(
                enumerate([10, 20]),
                metrics={'idx': ['d', tc.RAW], 'value': ['d', tc.RAW]},
                entry_fn=lambda index, item: {'idx': index, 'value': item[1]},
                show=False,
            )
        )
        self.assertEqual(items, [(0, 10), (1, 20)])

    def test_context_manager_finalizes_on_normal_exit(self):
        observed = []
        with tc.Dash(show=False) as dash:
            dash.finalize = lambda review=True: observed.append(review)
        self.assertEqual(observed, [True])

    def test_context_manager_skips_review_on_exception(self):
        observed = []
        dash = tc.Dash(show=False)
        dash.finalize = lambda review=True: observed.append(review)
        with self.assertRaises(RuntimeError):
            with dash:
                raise RuntimeError('boom')
        self.assertEqual(observed, [False])

    def test_old_format_argument_is_rejected(self):
        with self.assertRaises(AssertionError):
            tc.Dash(format={'n': ['d', tc.RAW]}, show=False)


class DashDisplayModeTests(QuietOutputMixin, unittest.TestCase):
    def _make_dash_with_state(self):
        dash = tc.Dash(show=False, metrics={'loss': ['.2f', tc.RAW], 'acc': ['.1f', tc.PERCENT]})
        dash.gauge_mile[('TRAIN', 'acc')] = [0.5]
        dash.gauge_mile[('TRAIN', 'loss')] = [1.0]
        dash.gauge_epoch[('TRAIN', 'acc')] = [0.5]
        dash.gauge_epoch[('TRAIN', 'loss')] = [1.0]
        dash.epoch_summaries.extend([f'epoch {i}' for i in range(1, 8)])
        dash._last_frame_state = {
            'stage': 'TRAIN',
            'epoch': 1,
            'mile': 1,
            'known_mpe': True,
            'mpe': 3,
            'items': [('TRAIN', 'acc'), ('TRAIN', 'loss')],
            'status_line': 'status',
            'status_line_inline': 'status',
            'status_line_fullscreen': 'status fs',
            'view_is_global': True,
            'view_is_elastic': False,
            'selected_metric_label': 'TRAIN:acc',
            'curve': '',
            'char_image': '',
            'plot': True,
            'curve_rows': 0,
            'image_rows': 0,
            'epoch_display': None,
            'epoch_visible_count': 0,
            'epoch_summaries': list(dash.epoch_summaries),
            'epoch_page': dash.epoch_page,
            'width': 100,
            'height': 40,
        }
        return dash

    def test_s_toggles_between_inline_and_fullscreen_when_available(self):
        dash = self._make_dash_with_state()
        dash._is_fullscreen_available = lambda: True
        dash._handle_key('s')
        self.assertEqual(dash.display_mode, 'fullscreen')
        dash._handle_key('s')
        self.assertEqual(dash.display_mode, 'inline')
        self.assertEqual(dash.focused_panel, 'curve')

    def test_s_warns_once_when_fullscreen_is_unavailable(self):
        dash = self._make_dash_with_state()
        dash._is_fullscreen_available = lambda: False
        dash._handle_key('s')
        self.assertTrue(dash.fullscreen_warned)
        self.assertEqual(dash.display_mode, 'inline')
        first_event_count = len(dash.events)
        dash._handle_key('s')
        self.assertEqual(len(dash.events), first_event_count)

    def test_q_only_exits_in_review_mode(self):
        dash = self._make_dash_with_state()
        dash._is_fullscreen_available = lambda: True
        dash._handle_key('q')
        self.assertEqual(dash.display_mode, 'inline')
        dash.review_mode = True
        dash._handle_key('q')
        self.assertTrue(dash._exit_review)

    def test_navigation_keys_update_view_state_in_inline_mode(self):
        dash = self._make_dash_with_state()
        dash._handle_key('j')
        self.assertEqual(dash.selected_metric_idx, 1)
        self.assertTrue(dash.inline_manual_metric)
        dash._handle_key('g')
        self.assertFalse(dash.is_global)
        dash._handle_key('e')
        self.assertTrue(dash.is_elastic)
        dash._handle_key('l')
        self.assertFalse(dash.log_panel_visible)
        dash._handle_key('i')
        self.assertFalse(dash.image_panel_visible)
        dash._handle_key('?')
        self.assertTrue(dash.help_visible)

    def test_arrow_keys_match_jk_navigation(self):
        dash = self._make_dash_with_state()
        dash._handle_key('\x1b[B')
        self.assertEqual(dash.selected_metric_idx, 1)
        self.assertTrue(dash.inline_manual_metric)
        dash._handle_key('\x1b[A')
        self.assertEqual(dash.selected_metric_idx, 0)

    def test_pending_input_decodes_up_down_arrows(self):
        dash = self._make_dash_with_state()
        dash._queue_key('\x1b')
        dash._queue_key('[')
        dash._queue_key('B')
        dash._process_pending_input()
        self.assertEqual(dash.selected_metric_idx, 1)

    def test_epoch_panel_supports_paged_navigation_in_fullscreen(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'fullscreen'
        dash.focused_panel = 'epochs'
        dash._handle_key('j')
        self.assertEqual(dash.epoch_page, 1)
        dash._handle_key('k')
        self.assertEqual(dash.epoch_page, 0)

    def test_t_toggles_focused_pane_collapsed_state(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'fullscreen'
        dash.focused_panel = 'epochs'
        dash._handle_key('t')
        self.assertIn('epochs', dash.collapsed_panes)
        dash._handle_key('t')
        self.assertNotIn('epochs', dash.collapsed_panes)

    def test_colon_opens_action_palette_in_fullscreen(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'fullscreen'
        dash._handle_key(':')
        self.assertTrue(dash.action_palette_open)

    def test_action_palette_enters_browse_drawer(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'fullscreen'
        dash._handle_key(':')
        dash._handle_key('\r')
        self.assertEqual(dash.drawer_mode, 'browse')
        self.assertEqual(dash.active_action, 'prepend_history')
        self.assertTrue(dash.drawer_entries)
        self.assertEqual(dash.drawer_entries[-1]['kind'], 'input')

    def test_action_palette_supports_arrow_navigation(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'fullscreen'
        dash._handle_key(':')
        dash._handle_key('\x1b[B')
        self.assertEqual(dash.action_idx, 1)
        dash._handle_key('\x1b[A')
        self.assertEqual(dash.action_idx, 0)

    def test_browse_drawer_supports_arrow_navigation(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'fullscreen'
        dash._start_browse_action('export_csv', start_path=os.getcwd())
        dash._handle_key('\x1b[B')
        self.assertEqual(dash.drawer_idx, 1)
        dash._handle_key('\x1b[A')
        self.assertEqual(dash.drawer_idx, 0)

    def test_browse_drawer_can_switch_to_path_input(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'fullscreen'
        dash._start_browse_action('export_csv', start_path=os.getcwd())
        expected = dash.drawer_entries[-1]['path']
        dash._handle_key('p')
        self.assertEqual(dash.input_mode, 'path')
        self.assertEqual(dash.active_action, 'export_csv')
        self.assertEqual(dash.input_buffer, expected)

    def test_enter_path_row_uses_same_seed_as_p_shortcut(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'fullscreen'
        dash._start_browse_action('export_csv', start_path=os.getcwd())
        expected = dash.drawer_entries[-1]['path']
        dash.drawer_idx = len(dash.drawer_entries) - 1
        dash._handle_key('\r')
        self.assertEqual(dash.input_mode, 'path')
        self.assertEqual(dash.input_buffer, expected)

    def test_execute_action_uses_selected_target_path(self):
        dash = self._make_dash_with_state()
        observed = []
        dash.export_csv = lambda subdir='', base_path=None: observed.append(base_path)
        target = os.path.abspath('tmp-export-target')
        dash._execute_action('export_csv', target)
        self.assertEqual(observed, [target])
        self.assertIn(target, dash.recent_targets)

    def test_path_candidates_include_matching_directories(self):
        dash = self._make_dash_with_state()
        work = tempfile.mkdtemp(prefix='tcurve-ui-')
        os.makedirs(os.path.join(work, 'alpha_dir'))
        os.makedirs(os.path.join(work, 'beta_dir'))
        prefix = os.path.join(work, 'alp')
        candidates = dash._path_candidates(prefix)
        self.assertTrue(any(candidate.endswith('alpha_dir' + os.sep) for candidate in candidates))

    def test_path_input_keeps_jk_as_text(self):
        dash = self._make_dash_with_state()
        dash._open_path_input('export_csv', seed='/tmp/abc')
        dash._handle_key('j')
        dash._handle_key('k')
        self.assertEqual(dash.input_buffer, '/tmp/abcjk')

    def test_path_input_enter_submits_typed_buffer(self):
        dash = self._make_dash_with_state()
        observed = []
        dash._execute_action = lambda action, target: observed.append((action, target))
        dash._open_path_input('export_csv', seed='/tmp/base')
        dash._handle_key('j')
        dash._handle_key('k')
        dash._handle_key('\r')
        self.assertEqual(observed, [('export_csv', '/tmp/basejk')])

    def test_colon_in_review_inline_switches_to_fullscreen_and_opens_actions(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'inline'
        dash.review_mode = True
        dash._is_fullscreen_available = lambda: True
        dash._handle_key(':')
        self.assertEqual(dash.display_mode, 'fullscreen')
        self.assertTrue(dash.action_palette_open)

    def test_start_review_mode_clears_stale_action_ui(self):
        dash = self._make_dash_with_state()
        dash.action_palette_open = True
        dash.drawer_mode = 'browse'
        dash.input_mode = 'path'
        dash.active_action = 'export_csv'
        dash._ensure_input_listener = lambda: None
        dash._render_last_state = lambda: None
        dash._start_review_mode()
        self.assertTrue(dash.review_mode)
        self.assertFalse(dash.action_palette_open)
        self.assertIsNone(dash.drawer_mode)
        self.assertIsNone(dash.input_mode)
        self.assertIsNone(dash.active_action)


    def test_finalize_inline_does_not_enter_review(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'inline'
        dash._clear_action_ui = lambda: setattr(dash, 'drawer_mode', None)
        dash.finalize(review=True)
        self.assertFalse(dash.review_mode)
        self.assertFalse(dash._exit_review)

    def test_finalize_inline_restores_cursor_once(self):
        dash = self._make_dash_with_state()
        dash.show = True
        dash.display_mode = 'inline'
        dash._is_interactive_terminal = lambda: True
        dash._inline_rewind_lines = 7

        dash.finalize(review=False)
        dash.finalize(review=False)

        self.assertEqual(self._stdout_buffer.getvalue(), '\033[7B')
        self.assertEqual(dash._inline_rewind_lines, 0)

    def test_finalize_inline_wipe_output_adds_newline(self):
        dash = self._make_dash_with_state()
        dash.show = True
        dash.display_mode = 'inline'
        dash._is_interactive_terminal = lambda: True
        dash._inline_needs_newline = True

        dash.finalize(review=False)

        self.assertEqual(self._stdout_buffer.getvalue(), '\n')

    def test_finalize_without_review_exits_fullscreen(self):
        dash = self._make_dash_with_state()
        dash.show = True
        dash.display_mode = 'fullscreen'
        dash._fullscreen_active = True
        dash._is_interactive_terminal = lambda: True

        dash.finalize(review=False)

        self.assertEqual(dash.display_mode, 'inline')
        self.assertIn('\033[?1049l', self._stdout_buffer.getvalue())

    def test_finalize_fullscreen_enters_review_loop_setup(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'fullscreen'
        dash._process_pending_input = lambda: setattr(dash, '_exit_review', True)
        dash.finalize(review=True)
        self.assertFalse(dash.review_mode)
        self.assertFalse(dash._exit_review)

    def test_inline_manual_metric_selection_overrides_auto_rotation(self):
        dash = tc.Dash(show=False, metrics={'loss': ['.2f', tc.RAW], 'acc': ['.1f', tc.PERCENT]})
        dash.gauge_mile[('TRAIN', 'acc')] = [0.5]
        dash.gauge_mile[('TRAIN', 'loss')] = [1.0]
        dash.inline_manual_metric = True
        dash.selected_metric_idx = 1
        metric_id = dash._select_inline_metric([('TRAIN', 'acc'), ('TRAIN', 'loss')], mile=10, interv=1, in_loop=(0, 1), last_for=1)
        self.assertEqual(metric_id, ('TRAIN', 'loss'))

    def test_status_line_includes_mode_badge(self):
        dash = tc.Dash(metrics={'loss': ['.2f', tc.RAW]})
        with redirect_stdout(io.StringIO()):
            dash({'loss': 1.0}, 0, 0, 3, stage='TRAIN', plot=False)
        self.assertIn('[inline global fixed]', dash._last_frame_state['status_line'])

    def test_fullscreen_status_line_preserves_colored_progress_bar(self):
        dash = tc.Dash(metrics={'loss': ['.2f', tc.RAW]})
        with redirect_stdout(io.StringIO()):
            dash({'loss': 1.0}, 0, 1, 4, stage='TRAIN', plot=False)
        self.assertIn('\x1b[43m', dash._last_frame_state['status_line_fullscreen'])
        self.assertNotIn('·', dash._last_frame_state['status_line_fullscreen'])

    def test_focus_order_follows_top_to_bottom_visible_panes(self):
        dash = self._make_dash_with_state()
        dash.char_image = 'img\n'
        dash.image_panel_visible = True
        dash.events.append('event')
        dash.help_visible = True
        self.assertEqual(dash._focus_order(), ['curve', 'epochs', 'image', 'logs', 'help'])

    def test_focus_order_uses_left_and_right_curve_when_split(self):
        dash = self._make_dash_with_state()
        dash.curve_split = True
        self.assertEqual(dash._focus_order()[:3], ['curve_left', 'curve_right', 'epochs'])

    def test_focus_order_includes_compare_pane_when_histories_exist(self):
        dash = self._make_dash_with_state()
        dash.compared_histories = [{'path': '/tmp/a', 'label': 'a', 'enabled': True, 'mile': {}, 'epoch': {}}]
        self.assertIn('compare', dash._focus_order())

    def test_focus_order_includes_resources_when_active(self):
        dash = self._make_dash_with_state()
        dash.resources_active = True
        self.assertIn('resources', dash._focus_order())

    def test_v_toggles_split_curve_view(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'fullscreen'
        dash._handle_key('v')
        self.assertTrue(dash.curve_split)
        self.assertEqual(dash.focused_panel, 'curve_left')
        dash._handle_key('v')
        self.assertFalse(dash.curve_split)
        self.assertEqual(dash.focused_panel, 'curve')

    def test_v_rejects_split_when_span_exceeds_half_terminal_width(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'fullscreen'
        dash.span = 61
        dash._get_terminal_size = lambda: (120, 40)
        dash._handle_key('v')
        self.assertFalse(dash.curve_split)
        self.assertTrue(dash.log_panel_visible)
        self.assertIn('span 61 exceeds half terminal width 60', dash.events[-1])

    def test_r_reports_disabled_resources(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'fullscreen'
        dash._handle_key('r')
        self.assertFalse(dash.resources_active)
        self.assertTrue(dash.log_panel_visible)
        self.assertIn('Set resources=True', dash.events[-1])

    def test_r_toggles_resource_monitor_when_enabled(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'fullscreen'
        dash.resources_enabled = True
        dash.resource_monitor = mock.Mock()
        dash.resource_monitor.snapshot.return_value = {'cpu': 12.0, 'memory': None, 'gpus': []}
        dash._handle_key('r')
        self.assertTrue(dash.resources_active)
        self.assertEqual(dash.resource_snapshot['cpu'], 12.0)
        dash.resource_monitor.snapshot.assert_called_once()
        dash._handle_key('r')
        self.assertFalse(dash.resources_active)
        self.assertIsNone(dash.resource_snapshot)

    def test_resource_snapshot_only_samples_when_active(self):
        dash = self._make_dash_with_state()
        dash.resource_monitor = mock.Mock()
        dash.resource_monitor.snapshot.return_value = {'cpu': 12.0, 'memory': None, 'gpus': []}
        dash._refresh_frame_state(dash._last_frame_state)
        dash.resource_monitor.snapshot.assert_not_called()
        dash.resources_active = True
        state = dash._refresh_frame_state(dash._last_frame_state)
        dash.resource_monitor.snapshot.assert_called_once()
        self.assertEqual(state['resource_snapshot']['cpu'], 12.0)

    def test_resource_lines_render_cpu_memory_and_gpu(self):
        dash = self._make_dash_with_state()
        lines = dash._resource_lines({
            'cpu': 12.3,
            'memory': {'percent': 45.6, 'used_gb': 7.0, 'total_gb': 16.0},
            'gpus': [{'index': 0, 'util': 78.0, 'temperature_c': 65.0, 'memory_used_mb': 4096.0, 'memory_total_mb': 8192.0}],
            'gpu_error': '',
        })
        self.assertEqual(lines[0], 'CPU   Util [\033[92m+\033[0m---------]  12.3% | Memory [\033[93m+++++\033[0m-----]  45.6% 7.0/16.0G')
        self.assertEqual(lines[1], 'GPU0  Util [\033[91m++++++++\033[0m--]  78.0% | T.Celsius  65°C  VRAM  [\033[93m+++++\033[0m-----] 4.0/8.0G')

    def test_resource_lines_show_gpu_error(self):
        dash = self._make_dash_with_state()
        lines = dash._resource_lines({'cpu': None, 'memory': None, 'gpus': [], 'gpu_error': 'NVML failed'})
        self.assertEqual(lines[0], 'CPU   Util [----------]    -- | Memory [----------]    --')
        self.assertIn('GPU  Util/T.Celsius/VRAM --  NVML failed', lines)

    def test_resource_bar_clamps_percent(self):
        dash = self._make_dash_with_state()
        self.assertEqual(dash._resource_bar(-1), '----------')
        self.assertEqual(dash._resource_bar(20), '\033[92m++\033[0m--------')
        self.assertEqual(dash._resource_bar(50), '\033[93m+++++\033[0m-----')
        self.assertEqual(dash._resource_bar(101), '\033[91m++++++++++\033[0m')

    def test_right_curve_focus_controls_right_side_state(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'fullscreen'
        dash.curve_split = True
        dash.focused_panel = 'curve_right'
        dash.curve_right_metric_idx = 0
        dash.curve_right_view_global = True
        dash.curve_right_view_elastic = False
        dash._handle_key('j')
        self.assertEqual(dash.curve_right_metric_idx, 1)
        dash._handle_key('g')
        self.assertFalse(dash.curve_right_view_global)
        dash._handle_key('e')
        self.assertTrue(dash.curve_right_view_elastic)

    def test_epochs_panel_stays_available_before_first_summary(self):
        dash = tc.Dash(show=False, metrics={'loss': ['.2f', tc.RAW]})
        dash._last_frame_state = {
            'items': [('TRAIN', 'loss')],
            'epoch_summaries': [],
        }
        self.assertIn('epochs', dash._focus_order())

    def test_distribute_block_heights_respects_short_panes(self):
        dash = self._make_dash_with_state()
        allocations = dash._distribute_block_heights([3, 10, 10], 12)
        self.assertEqual(allocations[0], 3)
        self.assertEqual(sum(allocations), 12)
        self.assertLessEqual(abs(allocations[1] - allocations[2]), 1)

    def test_distribute_block_heights_allows_large_image_when_others_are_collapsed(self):
        dash = self._make_dash_with_state()
        allocations = dash._distribute_block_heights([2, 2, 12], 16)
        self.assertEqual(allocations, [2, 2, 12])

    def test_pane_block_uses_full_box_focus_highlight(self):
        dash = self._make_dash_with_state()
        focused = dash._pane_block(30, 'Metrics', ['row'], True)
        unfocused = dash._pane_block(30, 'Metrics', ['row'], False)
        self.assertTrue(focused[0].startswith('┏'))
        self.assertIn('[1m Metrics ', focused[0])
        self.assertTrue(focused[-1].startswith('┗'))
        self.assertTrue(focused[1].startswith('┃ '))
        self.assertTrue(unfocused[0].startswith('┌ Metrics'))
        self.assertTrue(unfocused[-1].startswith('└'))
        self.assertTrue(unfocused[1].startswith('│ '))

    def test_pane_block_uses_dot_separator_for_detail(self):
        dash = self._make_dash_with_state()
        block = dash._pane_block(40, 'Curve', ['row'], False, 'TRAIN:acc · global')
        self.assertIn('Curve · TRAIN:acc · global', block[0])

    def test_pane_block_keeps_right_border_with_ansi_content(self):
        dash = self._make_dash_with_state()
        block = dash._pane_block(40, 'Curve', ['abc [43m   [0m xyz'], True)
        self.assertTrue(block[1].endswith('┃'))
        self.assertEqual(dash._display_width(block[1]), 40)
        self.assertIn('\x1b[43m', block[1])

    def test_workspace_width_uses_larger_lower_right_panel(self):
        dash = self._make_dash_with_state()
        workspace_width = dash._workspace_width(100)
        self.assertEqual(workspace_width, 42)
        self.assertEqual(100 - workspace_width - 1, 57)

    def test_workspace_renderer_switches_between_actions_browse_and_input(self):
        dash = self._make_dash_with_state()
        dash._open_action_palette()
        self.assertIn('Actions', dash._render_workspace_lines(33)[0])
        dash._start_browse_action('export_csv', start_path=os.getcwd())
        self.assertIn('Export Target', dash._render_workspace_lines(33)[0])
        dash._open_path_input('export_csv', seed='/tmp/path')
        self.assertIn('Export CSV to path', dash._render_workspace_lines(33)[0])


    def test_workspace_overlay_only_affects_lower_section(self):
        dash = self._make_dash_with_state()
        upper = ['top-a', 'top-b']
        lower = ['left-1', 'left-2']
        result = dash._overlay_right_drawer(lower, ['panel-1', 'panel-2'], 100, drawer_width=33)
        self.assertTrue(result[0].startswith('left-1'))
        self.assertEqual(upper, ['top-a', 'top-b'])


    def test_refresh_frame_state_rebuilds_curve_with_current_view_flags(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'fullscreen'
        dash.span = 20
        dash.divisor = 6
        dash._last_frame_state['plot'] = True
        dash._last_frame_state['curve'] = 'stale'
        dash.is_global = False
        refreshed = dash._refresh_frame_state(dash._last_frame_state)
        self.assertFalse(refreshed['view_is_global'])
        self.assertNotEqual(refreshed['curve'], 'stale')
        self.assertIn('TRAIN:acc', refreshed['selected_metric_label'])


    def test_current_view_flags_follow_single_source_view_state(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'fullscreen'
        dash._last_frame_state['plot'] = True
        dash.is_global = False
        dash.is_elastic = True
        refreshed = dash._refresh_frame_state(dash._last_frame_state)
        self.assertFalse(refreshed['view_is_global'])
        self.assertTrue(refreshed['view_is_elastic'])

    def test_render_last_state_uses_loaded_history_data(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'fullscreen'
        dash._last_frame_state['plot'] = True
        original_curve = dash._refresh_frame_state(dash._last_frame_state)['curve']
        dash.gauge_mile[('TRAIN', 'acc')] = [0.1, 0.2, 0.3, 0.4, 0.5]
        dash.trail_mile[('TRAIN', 'acc')] = [1, 2, 3, 4, 5]
        refreshed_curve = dash._refresh_frame_state(dash._last_frame_state)['curve']
        self.assertNotEqual(refreshed_curve, original_curve)

    def test_render_metric_curve_rejects_span_too_wide_for_terminal(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'inline'
        dash.span = 90
        with self.assertRaisesRegex(ValueError, 'span.*terminal width'):
            dash._render_metric_curve(('TRAIN', 'acc'), True, False, width=100, height=40)

    def test_render_metric_curve_rejects_divisor_too_tall_for_terminal(self):
        dash = self._make_dash_with_state()
        dash.display_mode = 'inline'
        dash.divisor = 40
        with self.assertRaisesRegex(ValueError, 'divisor.*terminal height'):
            dash._render_metric_curve(('TRAIN', 'acc'), True, False, width=120, height=40)

    def test_append_block_clips_body_but_keeps_box_closed(self):
        dash = self._make_dash_with_state()
        target = ['header']
        block = dash._pane_block(30, 'Image', ['row1', 'row2', 'row3', 'row4'], True)
        dash._append_block(target, block, max_lines=5, width=30, focused=True)
        self.assertEqual(len(target), 5)
        self.assertTrue(target[-2].startswith('┃ ...'))
        self.assertTrue(target[-1].startswith('┗'))

    def test_clip_block_respects_requested_quota(self):
        dash = self._make_dash_with_state()
        block = dash._pane_block(30, 'Epochs', ['row1', 'row2', 'row3', 'row4'], False)
        clipped = dash._clip_block(block, 4, 30, False)
        self.assertEqual(len(clipped), 4)
        self.assertTrue(clipped[0].startswith('┌'))
        self.assertTrue(clipped[-2].startswith('│ ...'))
        self.assertTrue(clipped[-1].startswith('└'))

    def test_clip_block_pads_to_fill_available_quota(self):
        dash = self._make_dash_with_state()
        block = dash._pane_block(30, 'Events', ['row1'], False)
        clipped = dash._clip_block(block, 6, 30, False, pad=True)
        self.assertEqual(len(clipped), 6)
        self.assertTrue(clipped[-2].startswith('│ '))
        self.assertTrue(clipped[-1].startswith('└'))


class CurveRenderTests(unittest.TestCase):
    def test_curve_rejects_invalid_span(self):
        with self.assertRaisesRegex(ValueError, 'span'):
            curve2str(np.array([0.5] * 12), divisor=6, span=9, is_global=True, is_elastic=False)

    def test_curve_rejects_invalid_divisor(self):
        with self.assertRaisesRegex(ValueError, 'divisor'):
            curve2str(np.array([0.5] * 12), divisor=0, span=12, is_global=True, is_elastic=False)

    def test_constant_curve_stays_visible_above_axis(self):
        rendered = curve2str(np.array([0.5] * 12), divisor=6, span=12, is_global=True, is_elastic=False)
        self.assertRegex(rendered, r'_{8,}')

    def test_curve_axis_arrow_uses_plain_triangle(self):
        rendered = curve2str(np.array([0.2, 0.4, 0.6, 0.8, 1.0, 0.7, 0.3, 0.2, 0.5, 0.9]), divisor=6, span=10, is_global=True, is_elastic=False)
        self.assertIn('▲', rendered)
        self.assertNotIn('▲︎', rendered)


class ResourceMonitorTests(unittest.TestCase):
    def test_snapshot_uses_cache_within_interval(self):
        monitor = ResourceMonitor(interval=10.0)
        with mock.patch.object(monitor, '_cpu_percent', return_value=1.0) as cpu, \
             mock.patch.object(monitor, '_memory_percent', return_value=None), \
             mock.patch.object(monitor, '_gpu_stats', return_value=[]):
            first = monitor.snapshot()
            second = monitor.snapshot()
        self.assertIs(first, second)
        self.assertEqual(cpu.call_count, 1)

    def test_gpu_stats_parses_nvidia_smi_csv(self):
        monitor = ResourceMonitor()
        result = mock.Mock()
        result.returncode = 0
        result.stdout = '0, 75, 66, 4096, 8192\n'
        with mock.patch('tcurve.resources.shutil.which', return_value='/usr/bin/nvidia-smi'), \
             mock.patch('tcurve.resources.subprocess.run', return_value=result):
            gpus = monitor._gpu_stats(now=1.0)
        self.assertEqual(gpus, [{'index': 0, 'util': 75.0, 'temperature_c': 66.0, 'memory_used_mb': 4096.0, 'memory_total_mb': 8192.0}])

    def test_gpu_stats_returns_empty_without_nvidia_smi(self):
        monitor = ResourceMonitor()
        with mock.patch('tcurve.resources.shutil.which', return_value=None):
            self.assertEqual(monitor._gpu_stats(now=1.0), [])
        self.assertEqual(monitor.gpu_error, 'nvidia-smi not found')

    def test_gpu_stats_keeps_nvidia_smi_error_message(self):
        monitor = ResourceMonitor()
        result = mock.Mock()
        result.returncode = 255
        result.stdout = 'Failed to initialize NVML: Unknown Error\n'
        result.stderr = ''
        with mock.patch('tcurve.resources.shutil.which', return_value='/usr/bin/nvidia-smi'), \
             mock.patch('tcurve.resources.subprocess.run', return_value=result):
            self.assertEqual(monitor._gpu_stats(now=1.0), [])
        self.assertEqual(monitor.gpu_error, 'Failed to initialize NVML: Unknown Error')


class DashFormatTests(QuietOutputMixin, unittest.TestCase):
    def test_custom_formatter_receives_full_signature(self):
        observed = []

        def formatter(value, epoch, mile, mpe, stage):
            observed.append((value, epoch, mile, mpe, stage))
            return f'{value}:{stage}'

        dash = tc.Dash(metrics={'value': [formatter, tc.CUSTOM]})
        with redirect_stdout(io.StringIO()):
            dash({'value': 3}, 0, 0, 1, plot=False)
        self.assertEqual(observed, [(3, 1, 1, 1, 'ITER'), (3, 1, -1, 1, 'ITER')])


class DashEpochSummaryTests(QuietOutputMixin, unittest.TestCase):
    def test_image_persists_after_epoch_end(self):
        dash = tc.Dash(metrics={'img': [lambda value, epoch, mile, mpe, stage: True, tc.IMAGE]})
        arr = np.ones((4, 4), dtype=np.float32)
        with redirect_stdout(io.StringIO()):
            dash({'img': arr}, 0, 0, 1, stage='TRAIN', plot=False)
        self.assertTrue(dash.char_image)
        self.assertGreater(dash.image_row, 0)

    def test_epoch_summaries_accumulate_across_epochs(self):
        dash = tc.Dash(metrics={'loss': ['.2f', tc.RAW]})
        with redirect_stdout(io.StringIO()):
            dash({'loss': 1.0}, 0, 0, 2, stage='TRAIN', plot=False)
            dash({'loss': 0.8}, 0, 1, 2, stage='TRAIN', plot=False)
            dash({'loss': 0.6}, 1, 0, 2, stage='TRAIN', plot=False)
            dash({'loss': 0.4}, 1, 1, 2, stage='TRAIN', plot=False)
        self.assertEqual(len(dash.epoch_summaries), 2)
        self.assertIn('1st Epoch', dash.epoch_summaries[0])
        self.assertIn('2nd Epoch', dash.epoch_summaries[1])
        self.assertEqual(dash._last_frame_state['epoch_summaries'][-1], dash.epoch_summaries[-1])

    def test_inline_epoch_summary_does_not_shift_down_by_history_count(self):
        dash = tc.Dash(metrics={'loss': ['.2f', tc.RAW]})
        dash({'loss': 1.0}, 0, 0, 1, stage='TRAIN', plot=False)
        self._stdout_buffer.seek(0)
        self._stdout_buffer.truncate(0)
        dash({'loss': 0.8}, 1, 0, 1, stage='TRAIN', plot=False)
        self.assertIn('1st Epoch', self._stdout_buffer.getvalue())
        self.assertIn('2nd Epoch', self._stdout_buffer.getvalue())

    def test_identical_epoch_data_produces_identical_epoch_averages(self):
        dash = tc.Dash(metrics={'acc': ['.1f', tc.PERCENT]})
        series = [0.2, 0.4, 0.6]
        with redirect_stdout(io.StringIO()):
            for epoch in range(3):
                for mile, value in enumerate(series):
                    dash({'acc': value}, epoch, mile, len(series), stage='TRAIN', plot=False)
        values = dash.gauge_epoch[('TRAIN', 'acc')]
        self.assertEqual(len(values), 3)
        self.assertAlmostEqual(values[0], values[1], places=12)
        self.assertAlmostEqual(values[1], values[2], places=12)


class DashLoggingTests(QuietOutputMixin, unittest.TestCase):
    def test_compare_history_adds_colored_overlay_for_matching_metric(self):
        work = tempfile.mkdtemp(prefix='tcurve-compare-')
        base = tc.Dash(log_dir=work, metrics={'loss': ['.2f', tc.RAW]})
        with redirect_stdout(io.StringIO()):
            for i, loss in enumerate([1.0, 0.8, 0.4]):
                base({'loss': loss}, 0, i, 3, stage='TRAIN', plot=False)

        compare_dir = os.path.join(work, 'compare')
        os.makedirs(compare_dir, exist_ok=True)
        other = tc.Dash(log_dir=work, metrics={'loss': ['.2f', tc.RAW]})
        with redirect_stdout(io.StringIO()):
            for i, loss in enumerate([0.2, 0.4, 0.6]):
                other({'loss': loss}, 0, i, 3, stage='TRAIN', plot=False)
        other.export_csv(base_path=compare_dir)

        matched = base.compare_history(compare_dir)
        self.assertEqual(matched, 1)
        self.assertEqual(len(base.compared_histories), 1)
        rendered = base._render_metric_curve(('TRAIN', 'loss'), True, False, 100, 40)
        self.assertIn('[9', rendered)

    def test_compare_history_rejects_unmatched_metric_names(self):
        work = tempfile.mkdtemp(prefix='tcurve-compare-miss-')
        base = tc.Dash(log_dir=work, metrics={'loss': ['.2f', tc.RAW]})
        with redirect_stdout(io.StringIO()):
            for i, loss in enumerate([1.0, 0.8, 0.4]):
                base({'loss': loss}, 0, i, 3, stage='TRAIN', plot=False)

        compare_dir = os.path.join(work, 'compare')
        os.makedirs(compare_dir, exist_ok=True)
        other = tc.Dash(log_dir=work, metrics={'acc': ['.1f', tc.PERCENT]})
        with redirect_stdout(io.StringIO()):
            for i, acc in enumerate([0.2, 0.4, 0.6]):
                other({'acc': acc}, 0, i, 3, stage='TRAIN', plot=False)
        other.export_csv(base_path=compare_dir)

        with self.assertRaises(ValueError):
            base.compare_history(compare_dir)

    def test_compare_curve_keeps_axis_arrow_at_top(self):
        work = tempfile.mkdtemp(prefix='tcurve-compare-arrow-')
        base = tc.Dash(log_dir=work, metrics={'loss': ['.2f', tc.RAW]})
        with redirect_stdout(io.StringIO()):
            for i, loss in enumerate([1.0, 0.8, 0.4]):
                base({'loss': loss}, 0, i, 3, stage='TRAIN', plot=False)

        compare_dir = os.path.join(work, 'compare')
        os.makedirs(compare_dir, exist_ok=True)
        other = tc.Dash(log_dir=work, metrics={'loss': ['.2f', tc.RAW]})
        with redirect_stdout(io.StringIO()):
            for i, loss in enumerate([0.2, 0.4, 0.6]):
                other({'loss': loss}, 0, i, 3, stage='TRAIN', plot=False)
        other.export_csv(base_path=compare_dir)

        base.compare_history(compare_dir)
        rendered = base._render_metric_curve(('TRAIN', 'loss'), True, False, 100, 40).splitlines()
        self.assertIn('▲', rendered[1])
        self.assertNotIn('▲', rendered[-2])

    def test_compare_pane_toggle_hides_overlay_series(self):
        work = tempfile.mkdtemp(prefix='tcurve-compare-toggle-')
        base = tc.Dash(log_dir=work, metrics={'loss': ['.2f', tc.RAW]})
        with redirect_stdout(io.StringIO()):
            for i, loss in enumerate([1.0, 0.8, 0.4]):
                base({'loss': loss}, 0, i, 3, stage='TRAIN', plot=False)

        compare_dir = os.path.join(work, 'compare')
        os.makedirs(compare_dir, exist_ok=True)
        other = tc.Dash(log_dir=work, metrics={'loss': ['.2f', tc.RAW]})
        with redirect_stdout(io.StringIO()):
            for i, loss in enumerate([0.2, 0.4, 0.6]):
                other({'loss': loss}, 0, i, 3, stage='TRAIN', plot=False)
        other.export_csv(base_path=compare_dir)

        base.compare_history(compare_dir)
        self.assertEqual(len(base._collect_compare_series(('TRAIN', 'loss'))), 1)
        base.display_mode = 'fullscreen'
        base.focused_panel = 'compare'
        base._handle_key(' ')
        self.assertEqual(len(base._collect_compare_series(('TRAIN', 'loss'))), 0)
        base._handle_key(' ')
        self.assertEqual(len(base._collect_compare_series(('TRAIN', 'loss'))), 1)

    def test_compare_pane_shows_colored_history_marker(self):
        dash = tc.Dash(show=False, metrics={'loss': ['.2f', tc.RAW]})
        dash.compared_histories = [{'path': '/tmp/compare_a', 'label': 'compare_a', 'enabled': True, 'mile': {}, 'epoch': {}}]
        lines = dash._render_compare_selector_lines(40)
        self.assertIn('■', lines[0])
        self.assertIn('[', lines[0])

    def test_known_total_logging_uses_tuple_metric_keys_and_history_roundtrip(self):
        work = tempfile.mkdtemp(prefix='tcurve-known-')
        dash = tc.Dash(log_dir=work, metrics={'loss': ['.2f', tc.RAW], 'acc': ['.1f', tc.PERCENT]})
        with redirect_stdout(io.StringIO()):
            for i, (loss, acc) in enumerate([(1.0, 0.5), (0.8, 0.6), (0.4, 0.75)]):
                dash({'loss': loss, 'acc': acc}, 0, i, 3, stage='TRAIN', plot=False)

        self.assertIn(('TRAIN', 'loss'), dash.gauge_mile)
        self.assertIn(('TRAIN', 'acc'), dash.trail_mile)
        self.assertEqual(dash.trail_mile[('TRAIN', 'loss')], [1, 2, 3])
        self.assertEqual(len(dash.gauge_epoch[('TRAIN', 'loss')]), 1)

        dash.export_csv(subdir='out')
        self.assertEqual(
            sorted(os.listdir(os.path.join(work, 'out'))),
            ['acc_TRAIN_epoch.csv', 'acc_TRAIN_mile.csv', 'loss_TRAIN_epoch.csv', 'loss_TRAIN_mile.csv'],
        )

        history = tc.Dash(log_dir=work, metrics={'loss': ['.2f', tc.RAW], 'acc': ['.1f', tc.PERCENT]})
        history.load_history(os.path.join(work, 'out'))
        self.assertEqual(sorted(history.gauge_mile.keys()), [('TRAIN', 'acc'), ('TRAIN', 'loss')])
        self.assertEqual(history.trail_mile[('TRAIN', 'loss')], [-2.0, -1.0, 0.0])

    def test_unknown_total_only_exports_mile_series(self):
        work = tempfile.mkdtemp(prefix='tcurve-unknown-')
        dash = tc.Dash(log_dir=work, metrics={'loss': ['.2f', tc.RAW]})
        with redirect_stdout(io.StringIO()):
            for i, loss in enumerate([1.0, 0.8, 0.4]):
                dash({'loss': loss}, 0, i, None, stage='TRAIN', plot=False)

        dash.export_csv(subdir='out')
        self.assertEqual(sorted(os.listdir(os.path.join(work, 'out'))), ['loss_TRAIN_mile.csv'])

    def test_plot_curves_runs_when_optional_dependencies_are_available(self):
        work = tempfile.mkdtemp(prefix='tcurve-plots-')
        dash = tc.Dash(log_dir=work, metrics={'loss': ['.2f', tc.RAW], 'acc': ['.1f', tc.PERCENT]})
        with redirect_stdout(io.StringIO()):
            for i, (loss, acc) in enumerate([(1.0, 0.5), (0.8, 0.6), (0.4, 0.75)]):
                dash({'loss': loss, 'acc': acc}, 0, i, 3, stage='TRAIN', plot=False)

        try:
            with redirect_stderr(io.StringIO()), warnings.catch_warnings():
                warnings.simplefilter('ignore', DeprecationWarning)
                dash.plot_curves(subdir='plots')
        except ImportError as exc:
            self.skipTest(str(exc))
        self.assertTrue(os.listdir(os.path.join(work, 'plots')))

    def test_plot_curves_uses_aligned_epoch_series(self):
        work = tempfile.mkdtemp(prefix='tcurve-plots-aligned-')
        dash = tc.Dash(log_dir=work, metrics={'loss': ['.2f', tc.RAW]})
        metric_id = ('TRAIN', 'loss')
        dash._ensure_metric_storage(metric_id)
        dash.gauge_mile[metric_id] = [1.0]
        dash.trail_mile[metric_id] = [1]
        dash.gauge_epoch[metric_id] = [1.0]
        dash.trail_epoch[metric_id] = []

        fig = mock.Mock()
        fig.add_subplot.return_value = mock.Mock()
        fake_plt = mock.Mock()
        fake_plt.figure.return_value = fig
        fake_pd = mock.Mock()
        fake_pd.DataFrame.side_effect = lambda *args, **kwargs: {'args': args, 'kwargs': kwargs}
        fake_sns = mock.Mock()

        with mock.patch('tcurve.dash._import_logging_deps', return_value=(fake_plt, fake_pd, fake_sns)):
            dash.plot_curves(subdir='plots')

        self.assertEqual(fake_sns.lineplot.call_count, 1)

    def test_plot_curves_supports_selection_and_grouping_macros(self):
        work = tempfile.mkdtemp(prefix='tcurve-plots-group-')
        dash = tc.Dash(log_dir=work, metrics={'loss': ['.2f', tc.RAW], 'acc': ['.1f', tc.PERCENT]})
        for metric_id, values in {
            ('TRAIN', 'loss'): [1.0, 0.8],
            ('VAL', 'loss'): [1.2, 0.9],
            ('TRAIN', 'acc'): [0.5, 0.7],
        }.items():
            dash._ensure_metric_storage(metric_id)
            dash.gauge_mile[metric_id] = values
            dash.trail_mile[metric_id] = [1, 2]

        fake_plt = mock.Mock()
        fake_plt.figure.return_value.add_subplot.return_value = mock.Mock()
        fake_pd = mock.Mock()
        fake_pd.DataFrame.side_effect = lambda *args, **kwargs: {'args': args, 'kwargs': kwargs}
        fake_sns = mock.Mock()

        with mock.patch('tcurve.dash._import_logging_deps', return_value=(fake_plt, fake_pd, fake_sns)):
            dash.plot_curves(subdir='plots', select=[('TRAIN', 'loss'), ('TRAIN', 'acc')], group_by=tc.NOTHING)

        saved = [os.path.basename(call.args[0]) for call in fake_plt.savefig.call_args_list]
        self.assertEqual(saved, ['all_0.7_mile_2.jpg'])
        self.assertEqual(fake_sns.lineplot.call_count, 2)

        fake_plt.reset_mock()
        fake_sns.reset_mock()
        with mock.patch('tcurve.dash._import_logging_deps', return_value=(fake_plt, fake_pd, fake_sns)):
            dash.plot_curves(subdir='plots', select=[('TRAIN', 'loss'), ('VAL', 'loss')], group_by=tc.METRIC)

        saved = [os.path.basename(call.args[0]) for call in fake_plt.savefig.call_args_list]
        self.assertEqual(saved, ['loss_0.9_mile_2.jpg'])
        self.assertEqual(fake_sns.lineplot.call_count, 2)

    def test_plot_curves_rejects_explicit_non_scalar_metric(self):
        work = tempfile.mkdtemp(prefix='tcurve-plots-nonscalar-')
        dash = tc.Dash(log_dir=work, metrics={'img': [lambda *args: True, tc.IMAGE]})
        metric_id = ('TRAIN', 'img')
        dash._ensure_metric_storage(metric_id)
        dash.gauge_mile[metric_id] = [1.0]
        dash.trail_mile[metric_id] = [1]

        with self.assertRaises(ValueError):
            dash.plot_curves(select=[metric_id])

    def test_log_exports_plots_and_csv(self):
        dash = tc.Dash(metrics={'loss': ['.2f', tc.RAW]})
        observed = []
        dash.plot_curves = lambda subdir='': observed.append(('plots', subdir))
        dash.export_csv = lambda subdir='': observed.append(('csv', subdir))
        dash.log(subdir='run')
        self.assertEqual(observed, [('plots', 'run'), ('csv', 'run')])


if __name__ == '__main__':
    unittest.main()
