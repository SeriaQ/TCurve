#!/usr/bin/env python
# -*- coding:utf-8 -*-
from .utils import curve2str
from .resources import ResourceMonitor
import atexit
from collections import deque
from collections.abc import Iterable
import numpy as np
import os
import re
import select
import shutil
import sys
from sys import stdout
import threading
import time
import unicodedata

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - unavailable on some platforms
    termios = None
    tty = None



RAW = 0
PERCENT = 1
INVIZ = 2
IMAGE = 3
CUSTOM = 4
SERIES = 10
METRIC = 11
STAGE = 12
NOTHING = 13


def _import_logging_deps():
    try:
        import matplotlib.pyplot as plt
        import pandas as pd
        import seaborn as sns
    except ImportError as exc:
        raise ImportError(
            'TCurve logging requires optional dependencies: pandas, matplotlib, seaborn.'
        ) from exc
    return plt, pd, sns


class Dash(object):
    palette = ['#F08080', '#00BFFF', '#FFFF00', '#2E8B57', '#6A5ACD', '#FFD700', '#808080']
    linestyle = ['-', '--', '-.', ':']
    char_pixel = "∎◙⧫●♠◕◍❅☢◭◮◔⎖✠⚙☮☒♾@$B8&WM#⦷⦶*mwap॥✝0QOo◇⨞u+/()?i!lI1[]|_;:࿒\"^∸⌯~⊷-⊸,'`.⋄· "
        
    def __init__(self, log_dir='./logbook', window=1, divisor=12, span=60, metrics=None, show=True, resources=False, **kwargs):
        '''
        Args:
        >| log_dir: a directory to store log files or an iterable
        >| windoe: the window length of moving average
        >| divisor: how many intervals on the vertical axis
        >| span: the width of horizontal axis
        >| metrics: a dict whose values are [display_format, mode], e.g. {'Acc': ['.1f', PERCENT]}
        >| show: whether to show in current process
        >| resources: whether fullscreen resource monitoring can be enabled with "r"
        '''
        if isinstance(log_dir, str):
            for k in kwargs.keys():
                raise AssertionError('TCURVE ERROR ៙ Dash does not take "%s" as argument.' % k)
            self.log_dir = log_dir
            if not os.path.exists(self.log_dir):
                os.makedirs(self.log_dir)
        elif isinstance(log_dir, Iterable):
            self.log_dir = None
            self.iterable = log_dir.__iter__()
            self.wrapper_kwargs = self._validate_wrapper_kwargs(kwargs)
            declared_mpe = self.wrapper_kwargs.get('mpe')
            if hasattr(log_dir, '__len__'):
                self.length = len(log_dir)
            elif declared_mpe is not None:
                assert declared_mpe > 0, 'TCURVE ERROR ៙ "mpe" must be positive when declared for an iterable wrapper.'
                self.length = declared_mpe
            else:
                self.length = None
            self.cnt = 0
        else:
            raise TypeError('TCURVE ERROR ៙ "log_dir" must be either a path string or an iterator.')
        self.show = show
        self.window = window
        self.divisor = divisor
        self.span = span
        self.metrics = metrics
        self.resources_enabled = bool(resources)
        self.resources_active = False
        self.resource_monitor = None
        self.resource_snapshot = None

        self.max_epoch = 0
        self.char_image = ''
        self.image_row = 0
        self.first_call = True # if it is the first call for self.__call__()
        self.prev_time = -1
        self.win_mile = {}
        self.gauge_mile = {}
        self.gauge_epoch = {}
        self.trail_mile = {}
        self.trail_epoch = {}
        self.ptr = 0
        self.view_state = {
            'curve_view_global': None,
            'curve_view_elastic': None,
            'selected_metric_idx': 0,
            'inline_manual_metric': False,
            'epoch_page': 0,
            'curve_split': False,
            'curve_right_metric_idx': 0,
            'curve_right_view_global': None,
            'curve_right_view_elastic': None,
            'compare_selection_idx': 0,
        }

        self.display_mode = 'inline'
        self.fullscreen_min_width = 100
        self.fullscreen_min_height = 28
        self.fullscreen_warned = False
        self.log_panel_visible = True
        self.image_panel_visible = True
        self.help_visible = False
        self.focused_panel = 'curve'
        self.events = deque(maxlen=12)
        self.epoch_summaries = deque(maxlen=12)
        self.collapsed_panes = set()
        self._pending_keys = []
        self._pending_key_lock = threading.Lock()
        self._input_thread = None
        self._input_stop = threading.Event()
        self._input_listener_started = False
        self._stdin_fd = None
        self._stdin_attrs = None
        self._restore_registered = False
        self._fullscreen_active = False
        self._last_frame_state = None
        self._inline_rewind_lines = 0
        self._inline_needs_newline = False
        self.review_mode = False
        self._exit_review = False

        self.action_items = [
            ('prepend_history', 'Prepend history…'),
            ('compare_history', 'Compare history…'),
            ('export_csv', 'Export CSV…'),
            ('save_plots', 'Save plots…'),
        ]
        self.ui_state = {
            'action_palette_open': False,
            'action_idx': 0,
            'active_action': None,
            'drawer_mode': None,
            'drawer_path': '',
            'drawer_target_path': '',
            'drawer_entries': [],
            'drawer_idx': 0,
            'input_mode': None,
            'input_prompt': '',
            'input_buffer': '',
            'input_candidates': [],
            'input_idx': 0,
        }
        self.loaded_histories = []
        self.prepended_histories = []
        self.compared_histories = []
        self.recent_targets = deque(maxlen=8)

    @property
    def is_global(self):
        return self.view_state['curve_view_global']

    @is_global.setter
    def is_global(self, value):
        self.view_state['curve_view_global'] = value

    @property
    def is_elastic(self):
        return self.view_state['curve_view_elastic']

    @is_elastic.setter
    def is_elastic(self, value):
        self.view_state['curve_view_elastic'] = value

    @property
    def selected_metric_idx(self):
        return self.view_state['selected_metric_idx']

    @selected_metric_idx.setter
    def selected_metric_idx(self, value):
        self.view_state['selected_metric_idx'] = value

    @property
    def inline_manual_metric(self):
        return self.view_state['inline_manual_metric']

    @inline_manual_metric.setter
    def inline_manual_metric(self, value):
        self.view_state['inline_manual_metric'] = value

    @property
    def epoch_page(self):
        return self.view_state['epoch_page']

    @epoch_page.setter
    def epoch_page(self, value):
        self.view_state['epoch_page'] = value

    @property
    def curve_split(self):
        return self.view_state['curve_split']

    @curve_split.setter
    def curve_split(self, value):
        self.view_state['curve_split'] = value

    @property
    def curve_right_metric_idx(self):
        return self.view_state['curve_right_metric_idx']

    @curve_right_metric_idx.setter
    def curve_right_metric_idx(self, value):
        self.view_state['curve_right_metric_idx'] = value

    @property
    def curve_right_view_global(self):
        return self.view_state['curve_right_view_global']

    @curve_right_view_global.setter
    def curve_right_view_global(self, value):
        self.view_state['curve_right_view_global'] = value

    @property
    def curve_right_view_elastic(self):
        return self.view_state['curve_right_view_elastic']

    @curve_right_view_elastic.setter
    def curve_right_view_elastic(self, value):
        self.view_state['curve_right_view_elastic'] = value

    @property
    def compare_selection_idx(self):
        return self.view_state['compare_selection_idx']

    @compare_selection_idx.setter
    def compare_selection_idx(self, value):
        self.view_state['compare_selection_idx'] = value

    @property
    def action_palette_open(self):
        return self.ui_state['action_palette_open']

    @action_palette_open.setter
    def action_palette_open(self, value):
        self.ui_state['action_palette_open'] = value

    @property
    def action_idx(self):
        return self.ui_state['action_idx']

    @action_idx.setter
    def action_idx(self, value):
        self.ui_state['action_idx'] = value

    @property
    def active_action(self):
        return self.ui_state['active_action']

    @active_action.setter
    def active_action(self, value):
        self.ui_state['active_action'] = value

    @property
    def drawer_mode(self):
        return self.ui_state['drawer_mode']

    @drawer_mode.setter
    def drawer_mode(self, value):
        self.ui_state['drawer_mode'] = value

    @property
    def drawer_path(self):
        return self.ui_state['drawer_path']

    @drawer_path.setter
    def drawer_path(self, value):
        self.ui_state['drawer_path'] = value

    @property
    def drawer_target_path(self):
        return self.ui_state['drawer_target_path']

    @drawer_target_path.setter
    def drawer_target_path(self, value):
        self.ui_state['drawer_target_path'] = value

    @property
    def drawer_entries(self):
        return self.ui_state['drawer_entries']

    @drawer_entries.setter
    def drawer_entries(self, value):
        self.ui_state['drawer_entries'] = value

    @property
    def drawer_idx(self):
        return self.ui_state['drawer_idx']

    @drawer_idx.setter
    def drawer_idx(self, value):
        self.ui_state['drawer_idx'] = value

    @property
    def input_mode(self):
        return self.ui_state['input_mode']

    @input_mode.setter
    def input_mode(self, value):
        self.ui_state['input_mode'] = value

    @property
    def input_prompt(self):
        return self.ui_state['input_prompt']

    @input_prompt.setter
    def input_prompt(self, value):
        self.ui_state['input_prompt'] = value

    @property
    def input_buffer(self):
        return self.ui_state['input_buffer']

    @input_buffer.setter
    def input_buffer(self, value):
        self.ui_state['input_buffer'] = value

    @property
    def input_candidates(self):
        return self.ui_state['input_candidates']

    @input_candidates.setter
    def input_candidates(self, value):
        self.ui_state['input_candidates'] = value

    @property
    def input_idx(self):
        return self.ui_state['input_idx']

    @input_idx.setter
    def input_idx(self, value):
        self.ui_state['input_idx'] = value

    def _get_ordinal(self, number):
        remainder = number % 10
        if remainder == 1:
            ordinal = 'st'
        elif remainder == 2:
            ordinal = 'nd'
        elif remainder == 3:
            ordinal = 'rd'
        else:
            ordinal = 'th'
        return ordinal

    # Backward-compatible alias for older internal references.
    def _getOridinal(self, number):
        return self._get_ordinal(number)

    def _validate_wrapper_kwargs(self, kwargs):
        allowed = {
            'entry_fn', 'epoch', 'mpe', 'stage', 'interv', 'duration', 'plot', 'wipe',
            'flush', 'is_global', 'is_elastic', 'in_loop', 'last_for'
        }
        for k in kwargs.keys():
            assert k in allowed, 'TCURVE ERROR ៙ Dash does not take "%s" as argument.' % k
        return dict(kwargs)

    def _make_entry(self, item):
        if 'entry_fn' in self.wrapper_kwargs:
            entry = self.wrapper_kwargs['entry_fn'](self.cnt, item)
        else:
            entry = item
        if entry is None:
            return {}
        if isinstance(entry, dict):
            return entry
        if self.metrics is None:
            if 'entry_fn' not in self.wrapper_kwargs:
                return {}
            raise TypeError(
                'TCURVE ERROR ៙ iterable wrapper without "metrics" requires "entry_fn" to return a dictionary entry.'
            )
        keys = list(self.metrics.keys())
        if isinstance(entry, (tuple, list)):
            if len(keys) == 1:
                raise TypeError(
                    'TCURVE ERROR ៙ iterable item for a single metric must be a scalar; please provide "entry_fn".'
                )
            if len(entry) != len(keys):
                raise ValueError(
                    'TCURVE ERROR ៙ iterable item does not match the number of metrics in "metrics".'
                )
            return dict(zip(keys, entry))
        if len(keys) == 1 and isinstance(entry, (str, bytes, int, float, bool, np.number)):
            return {keys[0]: entry}
        raise TypeError(
            'TCURVE ERROR ៙ iterable item cannot be mapped to dashboard metrics; please provide "entry_fn".'
        )

    def _metric_id(self, stage, entry):
        return (stage, entry)

    def _metric_label(self, metric_id):
        return '%s:%s' % metric_id

    def _parse_metric_label(self, label):
        if isinstance(label, tuple) and len(label) == 2:
            return label
        parts = str(label).split(':', 1)
        if len(parts) != 2:
            raise ValueError('TCURVE ERROR ៙ metric label must be in "stage:entry" format, but got %s.' % label)
        return tuple(parts)

    def _metric_token(self, value):
        return str(value).replace('/', '-')

    def _metric_value_format(self, entry):
        if self.metrics is not None and entry in self.metrics and isinstance(self.metrics[entry][0], str):
            return '%' + self.metrics[entry][0]
        return None

    def _format_logged_value(self, entry, value):
        form = self._metric_value_format(entry)
        if form is not None:
            return form % value
        if isinstance(value, (int, float, np.integer, np.floating)):
            return '%.3g' % value
        return str(value)

    def _ensure_metric_storage(self, metric_id):
        if metric_id not in self.win_mile:
            self.win_mile[metric_id] = np.zeros((self.window,))
            self.gauge_mile[metric_id] = []
            self.gauge_epoch[metric_id] = []
            self.trail_mile[metric_id] = []
            self.trail_epoch[metric_id] = []

    def _resolve_log_dir(self, subdir='', base_path=None):
        if base_path is not None:
            log_dir = os.path.abspath(os.path.expanduser(base_path))
            os.makedirs(log_dir, exist_ok=True)
            return log_dir
        if self.log_dir is None:
            raise ValueError('TCURVE ERROR ៙ iterable wrappers do not support log export because "log_dir" is not a directory.')
        if subdir:
            log_dir = os.path.join(self.log_dir, subdir)
            os.makedirs(log_dir, exist_ok=True)
            return log_dir
        return self.log_dir

    def _get_terminal_size(self):
        size = shutil.get_terminal_size(fallback=(120, 40))
        return size.columns, size.lines

    def _is_interactive_terminal(self):
        return bool(
            termios is not None and tty is not None and
            getattr(sys.stdin, 'isatty', lambda: False)() and
            getattr(sys.stdout, 'isatty', lambda: False)()
        )

    def _is_fullscreen_available(self):
        if not self._is_interactive_terminal():
            return False
        columns, lines = self._get_terminal_size()
        return columns >= self.fullscreen_min_width and lines >= self.fullscreen_min_height

    def _restore_input_mode(self):
        if self._stdin_fd is not None and self._stdin_attrs is not None and termios is not None:
            try:
                termios.tcsetattr(self._stdin_fd, termios.TCSADRAIN, self._stdin_attrs)
            except termios.error:
                pass
        self._stdin_fd = None
        self._stdin_attrs = None

    def _stop_input_listener(self):
        self._input_stop.set()
        thread = self._input_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.2)
        self._input_thread = None
        self._input_listener_started = False
        self._restore_input_mode()

    def _ensure_input_listener(self):
        if self._input_listener_started or not self.show or not self._is_interactive_terminal():
            return
        try:
            self._stdin_fd = sys.stdin.fileno()
            self._stdin_attrs = termios.tcgetattr(self._stdin_fd)
            tty.setcbreak(self._stdin_fd)
        except (AttributeError, OSError, termios.error):
            self._stdin_fd = None
            self._stdin_attrs = None
            return
        self._input_stop.clear()
        self._input_thread = threading.Thread(target=self._input_loop, daemon=True)
        self._input_thread.start()
        self._input_listener_started = True
        if not self._restore_registered:
            atexit.register(self._restore_input_mode)
            self._restore_registered = True

    def _queue_key(self, key):
        with self._pending_key_lock:
            self._pending_keys.append(key)

    def _input_loop(self):
        fd = self._stdin_fd
        while not self._input_stop.is_set() and fd is not None:
            try:
                ready, _, _ = select.select([fd], [], [], 0.1)
            except (OSError, ValueError):
                break
            if not ready:
                continue
            try:
                key = os.read(fd, 1).decode(errors='ignore')
            except OSError:
                break
            if key:
                self._queue_key(key)

    def _drain_pending_keys(self):
        with self._pending_key_lock:
            keys = list(self._pending_keys)
            self._pending_keys.clear()
        return keys

    def _set_display_mode(self, mode):
        if mode == self.display_mode:
            return True
        if mode == 'fullscreen' and not self._is_fullscreen_available():
            return False
        if self.show and self._is_interactive_terminal():
            if mode == 'fullscreen' and not self._fullscreen_active:
                stdout.write('\033[?1049h\033[2J\033[H')
                stdout.flush()
                self._fullscreen_active = True
            elif mode == 'inline' and self._fullscreen_active:
                stdout.write('\033[?1049l')
                stdout.flush()
                self._fullscreen_active = False
        else:
            self._fullscreen_active = mode == 'fullscreen'
        self.display_mode = mode
        return True

    def _push_event(self, message):
        stamp = time.strftime('%H:%M:%S')
        self.events.append(f'{stamp}  {message}')

    def _print_inline_notice(self, message):
        if self.show:
            print(message)

    def _timestamp_token(self):
        return time.strftime('%Y%m%d_%H%M%S')

    def _default_target_path(self, action):
        base = self.log_dir if isinstance(self.log_dir, str) else os.getcwd()
        if action in ('load_history', 'prepend_history', 'compare_history'):
            return base
        folder = 'exports' if action == 'export_csv' else 'plots'
        return os.path.join(base, folder, 'run_%s' % self._timestamp_token())

    def _workspace_open(self):
        return self.drawer_mode == 'browse' or self.action_palette_open or self.input_mode == 'path'

    def _workspace_width(self, width):
        desired = min(max(42, (width * 2) // 5), 56)
        max_workspace = max(0, width - 1 - 40)
        if max_workspace <= 0:
            return 0
        return min(desired, max_workspace)

    def _render_workspace_lines(self, width):
        if self.input_mode == 'path':
            return self._render_input_lines(width)
        if self.drawer_mode == 'browse':
            return self._render_browse_drawer_lines(width)
        if self.action_palette_open:
            return self._render_action_palette_lines(width)
        return []

    def _clear_action_ui(self):
        self.action_palette_open = False
        self.active_action = None
        self.drawer_mode = None
        self.drawer_path = ''
        self.drawer_target_path = ''
        self.drawer_entries = []
        self.drawer_idx = 0
        self.input_mode = None
        self.input_prompt = ''
        self.input_buffer = ''
        self.input_candidates = []
        self.input_idx = 0

    def _open_action_palette(self):
        self._clear_action_ui()
        self.action_palette_open = True
        self.action_idx = 0

    def _start_browse_action(self, action, start_path=None):
        self.action_palette_open = False
        self.active_action = action
        self.drawer_mode = 'browse'
        requested_path = os.path.abspath(os.path.expanduser(start_path or self._default_target_path(action)))
        self.drawer_target_path = requested_path
        self.drawer_path = requested_path if os.path.isdir(requested_path) else (os.path.dirname(requested_path) or os.getcwd())
        self._refresh_browse_entries()

    def _refresh_browse_entries(self):
        path = self.drawer_path or os.getcwd()
        path = os.path.abspath(os.path.expanduser(path))
        target_path = getattr(self, 'drawer_target_path', path)
        target_path = os.path.abspath(os.path.expanduser(target_path))
        entries = [
            {'kind': 'select', 'label': '✓ Use this directory', 'path': path},
        ]
        parent = os.path.dirname(path)
        if parent and parent != path:
            entries.append({'kind': 'up', 'label': '..', 'path': parent})
        try:
            names = sorted(
                name for name in os.listdir(path)
                if os.path.isdir(os.path.join(path, name))
            )
        except OSError:
            names = []
        for name in names:
            entries.append({'kind': 'dir', 'label': name + '/', 'path': os.path.join(path, name)})
        entries.append({'kind': 'input', 'label': '⌨ Enter path…', 'path': target_path})
        self.drawer_path = path
        self.drawer_entries = entries
        self.drawer_idx = min(self.drawer_idx, max(0, len(entries) - 1))

    def _open_path_input(self, action, seed=''):
        self.action_palette_open = False
        self.drawer_mode = None
        self.active_action = action
        self.input_mode = 'path'
        self.input_prompt = {
            'prepend_history': 'Prepend history from path',
            'compare_history': 'Compare history from path',
            'load_history': 'Prepend history from path',
            'export_csv': 'Export CSV to path',
            'save_plots': 'Save plots to path',
        }[action]
        self.input_buffer = seed or self._default_target_path(action)
        self._refresh_input_candidates()

    def _refresh_input_candidates(self):
        self.input_candidates = self._path_candidates(self.input_buffer)
        self.input_idx = min(self.input_idx, max(0, len(self.input_candidates) - 1))

    def _path_candidates(self, raw_path):
        suggestions = []
        raw_path = raw_path or ''
        expanded = os.path.expanduser(raw_path)
        absolute = os.path.isabs(expanded)
        if raw_path.endswith(os.sep) or (expanded and os.path.isdir(expanded)):
            base_dir = expanded if expanded else os.getcwd()
            prefix = ''
        else:
            base_dir = os.path.dirname(expanded) if expanded else os.getcwd()
            prefix = os.path.basename(expanded)
        if base_dir == '':
            base_dir = os.getcwd()
        try:
            names = sorted(os.listdir(base_dir))
        except OSError:
            names = []
        for name in names:
            if prefix and not name.startswith(prefix):
                continue
            full = os.path.join(base_dir, name)
            candidate = full if absolute else os.path.relpath(full, os.getcwd())
            if os.path.isdir(full):
                candidate += os.sep
            suggestions.append(candidate)
        if raw_path == '':
            for recent in reversed(self.recent_targets):
                if recent not in suggestions:
                    suggestions.insert(0, recent)
        return suggestions[:8]

    def _remember_target(self, path):
        if path not in self.recent_targets:
            self.recent_targets.append(path)

    def _execute_action(self, action, target):
        target = os.path.abspath(os.path.expanduser(target))
        effective_action = 'prepend_history' if action == 'load_history' else action
        try:
            if effective_action == 'prepend_history':
                self.prepend_history(target)
                if target not in self.loaded_histories:
                    self.loaded_histories.append(target)
                if target not in self.prepended_histories:
                    self.prepended_histories.append(target)
                self._push_event('Prepended history from %s.' % target)
            elif effective_action == 'compare_history':
                matched = self.compare_history(target)
                self._push_event('Compared history from %s (%d metrics).' % (target, matched))
            elif effective_action == 'export_csv':
                self.export_csv(base_path=target)
                self._push_event('Exported CSV to %s.' % target)
            elif effective_action == 'save_plots':
                self.plot_curves(base_path=target)
                self._push_event('Saved plots to %s.' % target)
            else:
                return
            self._remember_target(target)
        except Exception as exc:
            self._push_event('%s failed: %s' % (effective_action.replace('_', ' ').title(), exc))
        finally:
            self._clear_action_ui()

    def _render_action_palette_lines(self, width):
        body = ['Choose an action:', '']
        for idx, (_, label) in enumerate(self.action_items):
            marker = '>' if idx == self.action_idx else ' '
            body.append('%s %s' % (marker, label))
        body.extend(['', 'enter select  esc close'])
        return self._pane_block(width, 'Actions', body, True)

    def _render_browse_drawer_lines(self, width):
        path_label = self.drawer_path
        body = ['Path: %s' % path_label, '']
        for idx, entry in enumerate(self.drawer_entries):
            marker = '>' if idx == self.drawer_idx else ' '
            body.append('%s %s' % (marker, entry['label']))
        body.extend(['', 'enter open/select  p type path  esc close'])
        title = {
            'prepend_history': 'Prepend History',
            'compare_history': 'Compare History',
            'load_history': 'Prepend History',
            'export_csv': 'Export Target',
            'save_plots': 'Plot Target',
        }.get(self.active_action, 'Browser')
        return self._pane_block(width, title, body, True)

    def _render_input_lines(self, width):
        body = ['Type a path and press enter.', '', 'Path: %s' % self.input_buffer, '']
        if self.input_candidates:
            body.append('Suggestions:')
            for candidate in self.input_candidates[:5]:
                body.append('  %s' % candidate)
        else:
            body.append('Suggestions: none')
        body.extend(['', 'enter accept typed path  esc close'])
        return self._pane_block(width, self.input_prompt, body, True)

    def _overlay_right_drawer(self, lines, drawer_lines, width, drawer_width=None):
        if drawer_width is None:
            drawer_width = self._workspace_width(width)
        if drawer_width <= 0:
            return list(lines)
        main_width = max(1, width - drawer_width - 1)
        result = []
        total_rows = max(len(lines), len(drawer_lines))
        for idx in range(total_rows):
            base = self._fit_visible(lines[idx] if idx < len(lines) else '', main_width)
            drawer = self._fit_visible(drawer_lines[idx] if idx < len(drawer_lines) else '', drawer_width)
            result.append(base + ' ' + drawer)
        return result

    def _overlay_center_block(self, lines, block, width, top_row, total_rows=None):
        result = list(lines)
        target_rows = len(result) if total_rows is None else max(total_rows, len(result))
        while len(result) < target_rows:
            result.append('')
        left = max(0, (width - self._display_width(block[0])) // 2)
        for offset, row in enumerate(block):
            idx = top_row + offset
            if idx >= len(result):
                break
            result[idx] = ' ' * left + row
        return result

    def _focus_order(self):
        order = ['curve_left', 'curve_right'] if self.curve_split else ['curve']
        order.append('epochs')
        if self.compared_histories:
            order.append('compare')
        if self.resources_active:
            order.append('resources')
        if self.image_panel_visible and self.char_image:
            order.append('image')
        if self.log_panel_visible and self.events:
            order.append('logs')
        if self.help_visible:
            order.append('help')
        return order

    def _select_inline_metric(self, items, mile, interv, in_loop, last_for):
        metric_ids = self._current_metric_ids(items)
        if not metric_ids:
            return None
        if not self.inline_manual_metric and len(in_loop) > 1:
            if mile % (interv * last_for) == 0:
                self.ptr = (self.ptr + 1) % len(in_loop)
            metric_idx = in_loop[self.ptr]
            if metric_idx >= len(metric_ids):
                metric_idx = 0
            self.selected_metric_idx = metric_idx
        self.selected_metric_idx %= len(metric_ids)
        return metric_ids[self.selected_metric_idx]

    def _current_metric_ids(self, items=None):
        if self.gauge_mile:
            return sorted(self.gauge_mile.keys())
        if items is not None:
            return list(items)
        return []

    def _select_fullscreen_metric(self, items=None):
        metric_ids = self._current_metric_ids(items)
        if not metric_ids:
            return None
        self.selected_metric_idx %= len(metric_ids)
        return metric_ids[self.selected_metric_idx]

    def _metric_snapshot(self, metric_id):
        current = self.gauge_mile[metric_id][-1] if self.gauge_mile.get(metric_id) else None
        epoch = self.gauge_epoch[metric_id][-1] if self.gauge_epoch.get(metric_id) else None
        return current, epoch

    def _history_color_code(self, index):
        codes = ['[91m', '[94m', '[93m', '[92m', '[95m', '[33m', '[90m']
        return codes[index % len(codes)]

    def _read_history_dir(self, history):
        _, pd, _ = _import_logging_deps()
        series = {}
        for f in os.listdir(history):
            if not f.endswith('csv'):
                continue
            df = pd.read_csv(os.path.join(history, f), header=0)
            if len(df) == 0:
                continue
            unit = df.columns[0]
            raw_metric_id = self._parse_metric_label(df.columns[1])
            values = df.values
            if unit not in ('mile', 'epoch'):
                raise ValueError('TCURVE ERROR ៙ header is either to be "mile" or "epoch", but got %s.' % unit)
            metric_series = series.setdefault(raw_metric_id, {})
            metric_series[unit] = (values[:, 0].tolist(), values[:, 1].tolist())
        return series

    def _known_metric_ids(self, include_metrics=False):
        metric_ids = set(self.gauge_mile.keys()) | set(self.gauge_epoch.keys()) | set(self.trail_mile.keys()) | set(self.trail_epoch.keys())
        if include_metrics and self.metrics is not None:
            metric_ids |= {('ITER', entry) for entry in self.metrics.keys()}
        return sorted(metric_ids)

    def _resolve_history_metric_id(self, raw_metric_id, include_metrics=False):
        known_metric_ids = self._known_metric_ids(include_metrics=include_metrics)
        if raw_metric_id in known_metric_ids:
            return raw_metric_id
        same_entry = [metric_id for metric_id in known_metric_ids if metric_id[1] == raw_metric_id[1]]
        if len(same_entry) == 1:
            return same_entry[0]
        same_stage = [metric_id for metric_id in same_entry if metric_id[0] == raw_metric_id[0]]
        if len(same_stage) == 1:
            return same_stage[0]
        return None

    def _collect_compare_series(self, metric_id):
        compared = []
        for idx, item in enumerate(self.compared_histories):
            if not item.get('enabled', True):
                continue
            series = item.get('mile', {}).get(metric_id)
            if series is None:
                continue
            compared.append({
                'label': item['label'],
                'path': item['path'],
                'color': self._history_color_code(idx),
                'data': np.asarray(series[1], dtype=float),
            })
        return compared

    def _render_compare_selector_lines(self, width):
        if not self.compared_histories:
            return ['No compare histories loaded.']
        lines = []
        for idx, item in enumerate(self.compared_histories):
            marker = '>' if idx == self.compare_selection_idx else ' '
            checked = 'x' if item.get('enabled', True) else ' '
            label = item.get('label', os.path.basename(item['path']) or item['path'])
            color_chip = self._history_color_code(idx) + '■' + '[0m'
            lines.append(f"{marker} [{checked}] {color_chip} {label}")
        lines.append('')
        lines.append('enter/space toggle')
        return lines

    def _toggle_selected_compare_history(self):
        if not self.compared_histories:
            return
        self.compare_selection_idx %= len(self.compared_histories)
        item = self.compared_histories[self.compare_selection_idx]
        item['enabled'] = not item.get('enabled', True)
        self._push_event('Compare history %s %s.' % (item.get('label', item['path']), 'enabled' if item['enabled'] else 'hidden'))

    def _sample_curve(self, curve, span, is_global):
        curve = np.asarray(curve, dtype=float)
        if span < curve.size:
            if is_global:
                indices = [round(i * curve.size / span) for i in range(span)]
                curve = curve[indices]
                indices = [idx + 1 for idx in indices]
            else:
                indices = [curve.size - i for i in range(span, 0, -1)]
                curve = curve[-span:]
        else:
            indices = [i for i in range(1, span + 1)]
        return curve, indices

    def _quantize_curves(self, curves, divisor, is_elastic):
        merged_curve = np.concatenate(curves)
        y_max = merged_curve.max()
        y_min = merged_curve.min()
        delta = (y_max - y_min) / divisor if divisor > 0 else 0.0
        if delta == 0.0:
            return None, y_min, [np.zeros(curve.shape, dtype=np.int8) for curve in curves], [i for i in range(1, divisor + 1)]
        if is_elastic:
            merged_quant = np.clip(np.floor((merged_curve - y_min) / delta).astype(np.int8), 0, divisor - 1)
            hist = np.zeros(divisor)
            qualified = np.ones(divisor, dtype=np.int8)
            increment = 1.0 / max(1, merged_quant.size)
            for q in merged_quant:
                hist[q] += increment
            ascend = np.argsort(hist)
            portion = 1.0 / divisor
            merged = 0
            segment = 0
            contig = 0
            sum_h = 0
            last = -1
            for k, h in enumerate(hist):
                sum_h += h
                if sum_h < portion and k < divisor - 1:
                    contig += 1
                elif k == divisor - 1:
                    stop = k
                    if h < portion and contig > 0:
                        stop += 1
                    if h >= portion and contig == 1:
                        contig = 0
                    qualified[k - contig: stop] *= 0
                    merged += stop - (k - contig)
                    if stop - (k - contig) > 0 and (last < 0 or last != k - contig):
                        segment += 1
                else:
                    if contig > 1:
                        stop = k
                        if h < portion:
                            stop += 1
                        qualified[k - contig: stop] *= 0
                        merged += stop - (k - contig)
                        if last < 0 or last != k - contig:
                            segment += 1
                        last = stop
                        contig = 0
                        sum_h = 0
                    elif h < portion:
                        sum_h = h
                        contig = 1
                    else:
                        contig = 0
                        sum_h = 0
            delimiter = [0]
            denom = max(1, divisor - merged)
            quot = (merged - segment) % denom
            univ = (merged - segment) // denom
            qualified *= univ + 1
            if quot > 0:
                filled = 0
                for a in ascend[::-1]:
                    if filled == quot:
                        break
                    if qualified[a] > 0:
                        qualified[a] += 1
                        filled += 1
            quantized = []
            for curve in curves:
                quant = np.zeros(curve.shape, dtype=np.int8)
                m_ = -1
                _m = -1
                delimiter_local = [0]
                for k, q in enumerate(qualified):
                    if q == 0:
                        m_ = k if m_ < 0 else m_
                        _m = k
                    else:
                        if _m >= 0:
                            delimiter_local.append((_m + 1) * delta)
                            quant[curve - y_min - delimiter_local[-2] > 0] = len(delimiter_local) - 1
                        for j in range(q):
                            delimiter_local.append(k * delta + (j + 1) * delta / q)
                            quant[curve - y_min - delimiter_local[-2] > 0] = len(delimiter_local) - 1
                        m_ = -1
                        _m = -1
                if _m >= 0:
                    delimiter_local.append((_m + 1) * delta)
                    quant[curve - y_min - delimiter_local[-2] > 0] = len(delimiter_local) - 1
                quantized.append(quant)
            delimiter = delimiter_local[1:]
        else:
            quantized = [np.round((curve - y_min) / delta).astype(np.int8) for curve in curves]
            delimiter = [i * delta for i in range(1, divisor + 1)]
        return delta, y_min, quantized, delimiter

    def _render_compared_curve(self, metric_id, data, divisor, span, is_global, is_elastic, x_title, y_title):
        sampled_curves = []
        indices = None
        for curve in data:
            sampled, curve_indices = self._sample_curve(curve, span, is_global)
            sampled_curves.append(sampled)
            if indices is None:
                indices = curve_indices
        delta, y_min, quantized, delimiter = self._quantize_curves(sampled_curves, divisor, is_elastic)
        line_type = {'ascent': '/', 'descent': '\\', 'vertical': '|', 'horizontal': '_'}
        cells = [[{'char': ' ', 'color': None} for _ in range(span)] for _ in range(divisor)]

        def set_cell(row, col, char, color=None, primary=False):
            if row < 0 or row >= divisor or col < 0 or col >= span:
                return
            cell = cells[row][col]
            if primary or cell['char'] == ' ':
                cell['char'] = char
                cell['color'] = color

        compare_series = self._collect_compare_series(metric_id)
        color_sequence = [None] + [item['color'] for item in compare_series]
        if delta == 0.0:
            if divisor > 0:
                mid = min(max(divisor // 2, 0), divisor - 1)
                for series_idx, curve in enumerate(sampled_curves):
                    for col in range(min(span, curve.size)):
                        set_cell(mid, col, line_type['horizontal'], color_sequence[series_idx], primary=(series_idx == 0))
        else:
            for series_idx, quant in enumerate(quantized):
                color = color_sequence[series_idx]
                for i in range(max(0, quant.size - 1)):
                    prev = quant[i]
                    curr = quant[i + 1]
                    if prev > curr:
                        set_cell(prev - 1, i, line_type['descent'], color, primary=(series_idx == 0))
                        for j in range(1, prev - curr):
                            set_cell(prev - 1 - j, i, line_type['vertical'], color, primary=(series_idx == 0))
                    elif prev < curr:
                        set_cell(prev, i, line_type['ascent'], color, primary=(series_idx == 0))
                        for j in range(1, curr - prev):
                            set_cell(prev + j, i, line_type['vertical'], color, primary=(series_idx == 0))
                    else:
                        set_cell(prev, i, line_type['horizontal'], color, primary=(series_idx == 0))

        lines = [10 * ' ' + ' %s' % y_title, 10 * ' ' + ' ▲ ']
        for row in range(divisor - 1, -1, -1):
            if delta == 0.0:
                label = 10 * ' '
            else:
                label = f'{y_min + delimiter[row]:>10.3f}'
            line = label + ' ┃ '
            for cell in cells[row]:
                if cell['color'] is not None and cell['char'] != ' ':
                    line += cell['color'] + cell['char'] + '[0m'
                else:
                    line += cell['char']
            lines.append(line)
        lines.append(f'{y_min:>10.3f} ┗━' + span * '━' + ' ► %s' % x_title)
        x_domain = (10 + 3) * ' '
        for i in range(0, len(indices), 5):
            idx = indices[i]
            if idx < 1e3:
                x_domain += f'{idx:<4d} '
            elif idx < 1e4:
                x_domain += f'{idx / 1e3:<3.1f}K '
            elif idx < 1e6:
                x_domain += f'{round(idx / 1e3):<3d}K '
            elif idx < 1e7:
                x_domain += f'{idx / 1e6:<3.1f}M '
            elif idx < 1e9:
                x_domain += f'{round(idx / 1e6):<3d}M '
        lines.append(x_domain)
        return '\n'.join(lines) + '\n'

    def _render_metric_curve(self, metric_id, view_is_global, view_is_elastic, width, height):
        if metric_id is None or len(self.gauge_mile.get(metric_id, [])) == 0:
            return ''
        data = np.asarray(self.gauge_mile[metric_id], dtype=float)
        compared = self._collect_compare_series(metric_id)
        curves = [data] + [item['data'] for item in compared]
        curve_span = self.span if self.display_mode == 'inline' else max(30, min(width - 18, max(self.span, 40)))
        curve_divisor = self.divisor if self.display_mode == 'inline' else max(6, min(self.divisor + 4, max(height - 20, 6)))
        self._validate_curve_bounds(curve_span, curve_divisor, width, height)
        if len(curves) == 1:
            return curve2str(
                data,
                curve_divisor,
                curve_span,
                view_is_global,
                view_is_elastic,
                x_title='step',
                y_title=self._metric_label(metric_id) + 10 * ' ',
            )
        return self._render_compared_curve(
            metric_id,
            curves,
            curve_divisor,
            curve_span,
            view_is_global,
            view_is_elastic,
            'step',
            self._metric_label(metric_id) + 10 * ' ',
        )

    def _validate_curve_bounds(self, span, divisor, width, height):
        if span <= 9:
            raise ValueError('TCURVE ERROR ៙ "span" must be greater than 9, but got %d.' % span)
        if divisor <= 0:
            raise ValueError('TCURVE ERROR ៙ "divisor" must be positive, but got %d.' % divisor)
        required_width = span + 15
        if width > 0 and required_width > width:
            raise ValueError(
                'TCURVE ERROR ៙ "span" is too large for the terminal width: span=%d requires at least %d columns, but terminal width is %d.' %
                (span, required_width, width)
            )
        required_height = divisor + 4
        if height > 0 and required_height > height:
            raise ValueError(
                'TCURVE ERROR ៙ "divisor" is too large for the terminal height: divisor=%d requires at least %d rows, but terminal height is %d.' %
                (divisor, required_height, height)
            )

    def _strip_ansi(self, text):
        return re.sub(r'\x1b\[[0-9;]*m', '', str(text))

    def _display_width(self, text):
        width = 0
        for ch in self._strip_ansi(text):
            if unicodedata.combining(ch):
                continue
            width += 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
        return width

    def _fit_visible(self, text, width):
        text = str(text)
        out = []
        used = 0
        idx = 0
        ansi_re = re.compile(r'\x1b\[[0-9;]*m')
        while idx < len(text):
            match = ansi_re.match(text, idx)
            if match is not None:
                out.append(match.group(0))
                idx = match.end()
                continue
            ch = text[idx]
            idx += 1
            if unicodedata.combining(ch):
                continue
            ch_width = 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
            if used + ch_width > width:
                break
            out.append(ch)
            used += ch_width
        if used < width:
            out.append(' ' * (width - used))
        if '\x1b[' in text and (not out or not ''.join(out).endswith('\033[0m')):
            out.append('\033[0m')
        return ''.join(out)

    def _pane_border_chars(self, focused):
        if focused:
            return '┏', '┓', '┗', '┛', '━', '┃'
        return '┌', '┐', '└', '┘', '─', '│'

    def _pane_row(self, width, text, focused=False):
        _, _, _, _, _, vt = self._pane_border_chars(focused)
        content_width = max(1, width - 4)
        text_line = self._fit_visible(text, content_width)
        return vt + ' ' + text_line + ' ' + vt

    def _style_header(self, text, focused=False):
        if focused:
            return '\033[1m' + text + '\033[0m'
        return text

    def _pane_block(self, width, title, body_lines, focused=False, detail='', collapsed=False):
        label = title if detail == '' else f'{title} · {detail}'
        if collapsed:
            label = f'{label} · collapsed'
        tl, tr, bl, br, hz, vt = self._pane_border_chars(focused)
        inner = max(1, width - 2)
        header_plain = self._fit_visible(f' {label} ', inner)
        header_width = self._display_width(header_plain)
        header = self._style_header(header_plain, focused)
        top = tl + header + hz * max(0, inner - header_width) + tr
        block = [top]
        if not collapsed:
            if not body_lines:
                body_lines = ['']
            for line in body_lines:
                block.append(self._pane_row(width, line, focused))
        block.append(bl + hz * inner + br)
        return block

    def _clip_block(self, block, quota, width, focused=False, pad=False):
        if quota <= 0:
            return []
        if len(block) <= quota:
            if not pad or len(block) <= 2:
                return list(block)
            pad_rows = quota - len(block)
            if pad_rows <= 0:
                return list(block)
            padded = list(block[:-1])
            padded.extend(self._pane_row(width, '', focused) for _ in range(pad_rows))
            padded.append(block[-1])
            return padded
        if quota == 1:
            return [block[0]]
        if quota == 2:
            return [block[0], block[-1]]
        body_slots = quota - 2
        body = block[1:-1]
        clipped = body[:body_slots]
        if len(body) > body_slots and clipped:
            clipped[-1] = self._pane_row(width, '...', focused)
        return [block[0], *clipped, block[-1]]

    def _append_block(self, target_lines, block, max_lines, width, focused=False, pad=False):
        remaining = max_lines - len(target_lines)
        if remaining <= 0:
            return
        target_lines.extend(self._clip_block(block, remaining, width, focused, pad))

    def _distribute_block_heights(self, lengths, remaining):
        if not lengths or remaining <= 0:
            return [0] * len(lengths)
        total = sum(lengths)
        if total <= remaining:
            return list(lengths)
        allocations = [0] * len(lengths)
        pending = [idx for idx, length in enumerate(lengths) if length > 0]
        space = remaining
        while pending and space > 0:
            share = max(1, space // len(pending))
            progressed = False
            next_pending = []
            for idx in pending:
                need = lengths[idx] - allocations[idx]
                give = min(need, share)
                if give > 0:
                    allocations[idx] += give
                    space -= give
                    progressed = True
                if allocations[idx] < lengths[idx] and space > 0:
                    next_pending.append(idx)
                if space <= 0:
                    next_pending.extend(j for j in pending[pending.index(idx) + 1:] if allocations[j] < lengths[j])
                    break
            if not progressed:
                break
            pending = next_pending
        return allocations

    def _render_metric_lines(self, width, metric_ids):
        stage_width = 10
        metric_width = 12
        value_width = 10
        lines = [
            f"{' ':1} {'Stage':<{stage_width}} {'Metric':<{metric_width}} {'Now':<{value_width}} {'Epoch':<{value_width}}"[:width],
            f"{'-':1} {'-' * stage_width} {'-' * metric_width} {'-' * value_width} {'-' * value_width}"[:width],
        ]
        for idx, metric_id in enumerate(metric_ids):
            stage, entry = metric_id
            current, epoch = self._metric_snapshot(metric_id)
            marker = '>' if idx == self.selected_metric_idx else ' '
            current_text = '--' if current is None else self._format_logged_value(entry, current)
            epoch_text = '--' if epoch is None else self._format_logged_value(entry, epoch)
            line = f"{marker} {stage:<{stage_width}} {entry:<{metric_width}} {current_text:<{value_width}} {epoch_text:<{value_width}}"
            lines.append(line[:width])
        return lines

    def _render_help_lines(self, width):
        lines = [
            'Controls:',
            '  s switch inline/fullscreen',
            '  : open actions',
            '  q quit review after training ends',
            '  j/k or arrows select metric or page',
            '  g toggle global/recent curve view',
            '  e toggle elastic/fixed y-axis',
            '  v toggle split curve view',
            '  r toggle resource monitor',
            '  l toggle event panel',
            '  i toggle image panel',
            '  t collapse/expand focused pane',
            '  tab cycle focus panel',
            '  ? toggle this help panel',
        ]
        return [line[:width] for line in lines]

    def _render_curve_section_lines(self, section, width, height):
        metric_id = section['metric_id']
        mode = 'global' if section['view_is_global'] else 'recent'
        axis = 'elastic' if section['view_is_elastic'] else 'fixed'
        compare_count = section.get('compare_count', 0)
        focus_marker = '>' if self.focused_panel == section['focus'] else ' '
        label = f"{focus_marker} {section['label']} | {mode} | {axis}"
        if compare_count:
            label += f' | cmp {compare_count}'
        body = [label[:width]]
        curve_text = self._render_metric_curve(metric_id, section['view_is_global'], section['view_is_elastic'], width + 4, height)
        if curve_text:
            body.extend(curve_text.rstrip('\n').splitlines())
        else:
            body.append('No curve data.')
        return body

    def _ensure_resource_monitor(self):
        if self.resource_monitor is None:
            self.resource_monitor = ResourceMonitor()
        return self.resource_monitor

    def _toggle_resources(self):
        if not self.resources_enabled:
            self.log_panel_visible = True
            self._push_event('Resource monitor is disabled. Set resources=True to enable it.')
            return
        self.resources_active = not self.resources_active
        if self.resources_active:
            self._ensure_resource_monitor()
            self.resource_snapshot = None
            self._push_event('Resource monitor enabled.')
        else:
            self.resource_snapshot = None
            if self.focused_panel == 'resources':
                self.focused_panel = 'curve'
            self._push_event('Resource monitor disabled.')

    def _resource_lines(self, snapshot):
        if snapshot is None:
            return ['No resource sample yet.']
        lines = []
        cpu = snapshot.get('cpu')
        cpu_text = self._resource_util_text('CPU', cpu)
        memory = snapshot.get('memory')
        if memory is None:
            memory_text = 'Memory [----------]    --'
        else:
            memory_text = (
                'Memory [%s] %5.1f%% %.1f/%.1fG' %
                (self._resource_bar(memory['percent']), memory['percent'], memory['used_gb'], memory['total_gb'])
            )
        lines.append('%s | %s' % (cpu_text, memory_text))
        gpus = snapshot.get('gpus') or []
        if not gpus:
            gpu_error = snapshot.get('gpu_error')
            if gpu_error:
                lines.append('GPU  Util/T.Celsius/VRAM --  %s' % gpu_error)
            else:
                lines.append('GPU  Util/T.Celsius/VRAM --')
        else:
            for gpu in gpus:
                used_gb = gpu['memory_used_mb'] / 1024.0
                total_gb = gpu['memory_total_mb'] / 1024.0
                vram_percent = 0.0 if total_gb <= 0 else min(100.0, max(0.0, used_gb / total_gb * 100.0))
                lines.append(
                    '%s | T.Celsius %3.0f°C  VRAM  [%s] %.1f/%.1fG' %
                    (
                        self._resource_util_text('GPU%d' % gpu['index'], gpu['util']),
                        gpu['temperature_c'],
                        self._resource_bar(vram_percent),
                        used_gb,
                        total_gb,
                    )
                )
        return lines

    def _resource_util_text(self, name, percent):
        if percent is None:
            return '%-5s Util [----------]    --' % name
        return '%-5s Util [%s] %5.1f%%' % (name, self._resource_bar(percent), percent)

    def _resource_bar(self, percent, width=10):
        filled = int(round(min(100.0, max(0.0, percent)) / 100.0 * width))
        if filled <= 0:
            return '-' * width
        if 1 <= filled <= 3:
            color = '\033[92m'
        elif 4 <= filled <= 7:
            color = '\033[93m'
        else:
            color = '\033[91m'
        return color + '+' * filled + '\033[0m' + '-' * (width - filled)

    def _render_split_curve_body(self, state, width, height):
        usable_width = max(24, width)
        left_width = max(24, (usable_width - 3) // 2)
        right_width = max(24, usable_width - 3 - left_width)
        sections = state.get('curve_sections', [])[:2]
        left_lines = self._render_curve_section_lines(sections[0], left_width, height) if sections else ['No curve data.']
        right_lines = self._render_curve_section_lines(sections[1], right_width, height) if len(sections) > 1 else ['No curve data.']
        total_rows = max(len(left_lines), len(right_lines))
        body = []
        for idx in range(total_rows):
            left = self._fit_visible(left_lines[idx] if idx < len(left_lines) else '', left_width)
            right = self._fit_visible(right_lines[idx] if idx < len(right_lines) else '', right_width)
            body.append(left + ' │ ' + right)
        fullscreen_status = state.get('status_line_fullscreen', state.get('status_line', ''))
        if fullscreen_status:
            body.append('')
            body.append(fullscreen_status[:max(1, usable_width)])
        return body

    def _render_fullscreen(self, state):
        if not self._fullscreen_active:
            self._set_display_mode('fullscreen')
        width, height = self._get_terminal_size()
        lines = []
        max_lines = max(1, height - 1)
        resource_state = 'on' if self.resources_active else 'off'
        lines.append(('TCurve Fullscreen | prepend %d | compare %d | resources %s' % (len(self.prepended_histories), len(self.compared_histories), resource_state))[:width])
        switch_hint = '[s] inline'
        quit_hint = ' [q] quit' if self.review_mode else ''
        lines.append(f"controls [: actions] [tab pane] [j/k act] [g view] [e axis] [v split] [r res] [l events] [i image] [t toggle] [ ? help ] {switch_hint}{quit_hint}"[:width])
        lines.append('-' * width)

        curve_focused = self.focused_panel in ('curve', 'curve_left', 'curve_right')
        if state.get('curve_split_active'):
            curve_lines = self._render_split_curve_body(state, max(1, width - 4), height)
            curve_detail = 'split view'
        else:
            mode = 'global' if state['view_is_global'] else 'recent'
            axis = 'elastic' if state['view_is_elastic'] else 'fixed'
            curve_lines = []
            if state['curve']:
                curve_lines.extend(state['curve'].rstrip('\n').splitlines())
            fullscreen_status = state.get('status_line_fullscreen', state.get('status_line', ''))
            if fullscreen_status:
                if curve_lines:
                    curve_lines.append('')
                curve_lines.append(fullscreen_status[:max(1, width - 4)])
            curve_detail = f"{state['selected_metric_label']} | {mode} | {axis}"
            curve_sections = state.get('curve_sections', [])
            compare_count = curve_sections[0].get('compare_count', 0) if curve_sections else 0
            if compare_count:
                curve_detail += f' | cmp {compare_count}'
        curve_block = self._pane_block(
            width,
            'Curve',
            curve_lines,
            curve_focused,
            curve_detail,
            collapsed='curve' in self.collapsed_panes,
        )
        self._append_block(lines, curve_block, max_lines, width, curve_focused, pad=False)

        lower_start = len(lines)
        workspace_width = self._workspace_width(width) if self._workspace_open() else 0
        lower_width = width if workspace_width <= 0 else max(1, width - workspace_width - 1)

        other_blocks = []
        epoch_history = list(state.get('epoch_summaries', []))
        page_size = 5
        total_pages = max(1, (len(epoch_history) + page_size - 1) // page_size)
        page = min(max(state.get('epoch_page', 0), 0), total_pages - 1)
        if epoch_history:
            end = len(epoch_history) - page * page_size
            start = max(0, end - page_size)
            epoch_body = [line[:max(1, lower_width - 4)] for line in epoch_history[start:end]]
            epoch_detail = f'{start + 1}-{end}/{len(epoch_history)} | page {page + 1}/{total_pages}'
        else:
            epoch_body = ['No epoch summaries yet.']
            epoch_detail = '0/0 | page 1/1'
        other_blocks.append((
            self._pane_block(
                lower_width,
                'Epochs',
                epoch_body,
                self.focused_panel == 'epochs',
                epoch_detail,
                collapsed='epochs' in self.collapsed_panes,
            ),
            self.focused_panel == 'epochs',
        ))

        if self.compared_histories:
            compare_detail = f"{sum(1 for item in self.compared_histories if item.get('enabled', True))}/{len(self.compared_histories)} visible"
            other_blocks.append((
                self._pane_block(
                    lower_width,
                    'Compare',
                    self._render_compare_selector_lines(max(1, lower_width - 4)),
                    self.focused_panel == 'compare',
                    compare_detail,
                    collapsed='compare' in self.collapsed_panes,
                ),
                self.focused_panel == 'compare',
            ))

        if self.resources_active:
            other_blocks.append((
                self._pane_block(
                    lower_width,
                    'Resources',
                    self._resource_lines(state.get('resource_snapshot')),
                    self.focused_panel == 'resources',
                    collapsed='resources' in self.collapsed_panes,
                ),
                self.focused_panel == 'resources',
            ))

        if self.image_panel_visible and state['char_image']:
            other_blocks.append((
                self._pane_block(
                    lower_width,
                    'Image',
                    state['char_image'].rstrip('\n').splitlines(),
                    self.focused_panel == 'image',
                    collapsed='image' in self.collapsed_panes,
                ),
                self.focused_panel == 'image',
            ))
        if self.log_panel_visible and self.events:
            other_blocks.append((
                self._pane_block(
                    lower_width,
                    'Events',
                    list(self.events)[-6:],
                    self.focused_panel == 'logs',
                    collapsed='logs' in self.collapsed_panes,
                ),
                self.focused_panel == 'logs',
            ))
        if self.help_visible:
            other_blocks.append((
                self._pane_block(
                    lower_width,
                    'Help',
                    self._render_help_lines(max(1, lower_width - 4)),
                    self.focused_panel == 'help',
                    collapsed='help' in self.collapsed_panes,
                ),
                self.focused_panel == 'help',
            ))

        remaining = max_lines - len(lines)
        quotas = self._distribute_block_heights([len(block) for block, _ in other_blocks], remaining)
        for (block, focused), quota in zip(other_blocks, quotas):
            if quota <= 0:
                continue
            lines.extend(self._clip_block(block, quota, lower_width, focused, pad=False))

        output_lines = lines[:max_lines]
        if workspace_width > 0:
            workspace_lines = self._render_workspace_lines(workspace_width)
            upper_lines = output_lines[:lower_start]
            lower_lines = output_lines[lower_start:]
            lower_overlay = self._overlay_right_drawer(lower_lines, workspace_lines, width, drawer_width=workspace_width)
            output_lines = (upper_lines + lower_overlay)[:max_lines]

        stdout.write('\033[H\033[2J' + '\n'.join(output_lines))
        stdout.flush()

    def _render_inline(self, state, wipe=False, flush=0):
        if state['curve']:
            print(state['curve'])
        if state['char_image']:
            print(state['char_image'])
        print(state['width'] * ' ', end='\r')
        end_char = '\r' if wipe else '\n'
        line = state.get('status_line_inline', state['status_line'])
        if self._is_interactive_terminal():
            line += ' [s fullscreen]'
            if self.review_mode:
                line += ' [q quit]'
        print(line, end=end_char)
        summary_lines = []
        if not wipe:
            for display in state.get('epoch_summaries', []):
                border = '+' + max(1, self._display_width(display) - 2) * '-' + '+' + 30 * ' '
                summary_lines.extend([border, display, border])
            for summary_line in summary_lines:
                print(summary_line)
        rewind_lines = 0
        if wipe:
            self._inline_rewind_lines = 0
            self._inline_needs_newline = True
            stdout.flush()
        else:
            if state['curve']:
                rewind_lines = state['curve_rows'] + flush + state['image_rows'] + 2 + len(summary_lines)
            else:
                rewind_lines = state['image_rows'] + 1 + len(summary_lines)
            stdout.write(f"\033[{rewind_lines}A")
            stdout.flush()
            self._inline_rewind_lines = rewind_lines
            self._inline_needs_newline = False

    def _finish_inline(self):
        if not self._inline_rewind_lines and not self._inline_needs_newline:
            return
        if self._is_interactive_terminal():
            if self._inline_rewind_lines:
                stdout.write(f"\033[{self._inline_rewind_lines}B")
            elif self._inline_needs_newline:
                stdout.write('\n')
            stdout.flush()
        self._inline_rewind_lines = 0
        self._inline_needs_newline = False

    def _current_view_flags(self, base_state=None):
        return self._current_view_flags_for_side('left', base_state)

    def _current_view_flags_for_side(self, side, base_state=None):
        if side == 'right':
            global_key = 'curve_right_view_global'
            elastic_key = 'curve_right_view_elastic'
            state_global = self.curve_right_view_global
            state_elastic = self.curve_right_view_elastic
            default_global_key = 'default_curve_right_view_is_global'
            default_elastic_key = 'default_curve_right_view_is_elastic'
        else:
            global_key = 'view_is_global'
            elastic_key = 'view_is_elastic'
            state_global = self.is_global
            state_elastic = self.is_elastic
            default_global_key = 'default_view_is_global'
            default_elastic_key = 'default_view_is_elastic'
        if base_state is None:
            default_global = True
            default_elastic = False
        else:
            default_global = base_state.get(global_key, base_state.get(default_global_key, True))
            default_elastic = base_state.get(elastic_key, base_state.get(default_elastic_key, False))
        view_is_global = default_global if state_global is None else state_global
        view_is_elastic = default_elastic if state_elastic is None else state_elastic
        return view_is_global, view_is_elastic

    def _current_curve_side(self):
        if self.display_mode == 'fullscreen' and self.curve_split and self.focused_panel == 'curve_right':
            return 'right'
        return 'left'

    def _toggle_curve_split(self):
        metric_ids = self._current_metric_ids(self._last_frame_state['items'] if self._last_frame_state is not None else None)
        if len(metric_ids) < 2:
            self._push_event('Split curve view requires at least two metrics.')
            return
        width, _ = self._get_terminal_size()
        if self.span > width / 2:
            self.log_panel_visible = True
            self._push_event('Split curve view disabled: span %d exceeds half terminal width %d.' % (self.span, width // 2))
            return
        self.curve_split = not self.curve_split
        if self.curve_split:
            left_idx = self.selected_metric_idx % len(metric_ids)
            right_idx = self.curve_right_metric_idx % len(metric_ids)
            if right_idx == left_idx:
                right_idx = (left_idx + 1) % len(metric_ids)
            self.curve_right_metric_idx = right_idx
            if self.curve_right_view_global is None:
                self.curve_right_view_global = self.is_global
            if self.curve_right_view_elastic is None:
                self.curve_right_view_elastic = self.is_elastic
            self.focused_panel = 'curve_left'
            self._push_event('Curve split view enabled.')
        else:
            if self.focused_panel in ('curve_left', 'curve_right'):
                self.focused_panel = 'curve'
            self._push_event('Curve split view disabled.')

    def _build_status_lines(self, state):
        if 'duration' not in state or 'ordinal' not in state or 'string_mile' not in state:
            inline_line = state.get('status_line_inline', state.get('status_line', ''))
            fullscreen_line = state.get('status_line_fullscreen', inline_line)
            return inline_line, fullscreen_line
        epoch = state['epoch']
        mile = state['mile']
        mpe = state['mpe']
        known_mpe = state['known_mpe']
        interv = state.get('interv', 1)
        if known_mpe:
            progress = int((mile - 1) / mpe * 20 + 0.4)
            pre_bar = ''
            yellow_bar = progress * ' '
            space_bar = (20 - progress) * ' '
        else:
            progress = ((mile - 1) // interv % 40) - 20
            progress = 20 + progress if progress < 0 else 19 - progress
            pre_bar = progress * ' '
            yellow_bar = ' '
            space_bar = (19 - progress) * ' '
        mode_badge = '[%s %s %s]' % (
            self.display_mode,
            'global' if state['view_is_global'] else 'recent',
            'elastic' if state['view_is_elastic'] else 'fixed',
        )
        status_suffix = mode_badge if self.display_mode == 'inline' else ''
        string_mile = state.get('string_mile', '')
        duration = state['duration']
        status_line_inline = '| %d%s Epoch ⚘ %d Miles ≺[%s[43m%s[0m%s]≻ ₪ %ss/mile | %s |%s %s     ' % (
            epoch,
            state['ordinal'],
            mile,
            pre_bar,
            yellow_bar,
            space_bar,
            duration,
            state['stage'],
            string_mile,
            status_suffix,
        )
        status_line_fullscreen = '| %d%s Epoch ⚘ %d Miles ≺[%s[43m%s[0m%s]≻ ₪ %ss/mile | %s |%s     ' % (
            epoch,
            state['ordinal'],
            mile,
            pre_bar,
            yellow_bar,
            space_bar,
            duration,
            state['stage'],
            string_mile,
        )
        return status_line_inline, status_line_fullscreen

    def _build_frame_state(self, base_state):
        state = dict(base_state)
        width, height = self._get_terminal_size()
        state['width'] = max(1, width - 1)
        state['height'] = height
        metric_ids = self._current_metric_ids(state.get('items'))
        state['metric_ids'] = metric_ids
        selected_metric_id = None
        if metric_ids:
            self.selected_metric_idx %= len(metric_ids)
            selected_metric_id = metric_ids[self.selected_metric_idx]
        state['selected_metric'] = selected_metric_id
        state['selected_metric_label'] = self._metric_label(selected_metric_id) if selected_metric_id is not None else 'none'
        view_is_global, view_is_elastic = self._current_view_flags(state)
        state['view_is_global'] = view_is_global
        state['view_is_elastic'] = view_is_elastic
        curve_split_active = self.display_mode == 'fullscreen' and self.curve_split and len(metric_ids) > 1
        state['curve_split_active'] = curve_split_active
        state['epoch_summaries'] = list(self.epoch_summaries)
        state['epoch_summary_offset'] = len(self.epoch_summaries)
        state['epoch_page'] = self.epoch_page
        state['char_image'] = self.char_image
        state['image_rows'] = self.image_row
        state['compare_history_count'] = len(self.compared_histories)
        state['prepend_history_count'] = len(self.prepended_histories)
        self.resource_snapshot = self._ensure_resource_monitor().snapshot() if self.resources_active else None
        state['resource_snapshot'] = self.resource_snapshot
        plot = state.get('plot', True)
        curve = ''
        curve_rows = 0
        curve_sections = []
        if selected_metric_id is not None and plot:
            curve = self._render_metric_curve(selected_metric_id, view_is_global, view_is_elastic, width, height)
            curve_rows = len(curve.rstrip('\n').splitlines()) if curve else 0
            curve_sections.append({
                'focus': 'curve_left' if curve_split_active else 'curve',
                'metric_id': selected_metric_id,
                'label': self._metric_label(selected_metric_id),
                'view_is_global': view_is_global,
                'view_is_elastic': view_is_elastic,
                'compare_count': len(self._collect_compare_series(selected_metric_id)),
            })
        if curve_split_active:
            self.curve_right_metric_idx %= len(metric_ids)
            right_metric_id = metric_ids[self.curve_right_metric_idx]
            right_view_is_global, right_view_is_elastic = self._current_view_flags_for_side('right', state)
            state['curve_right_metric_id'] = right_metric_id
            state['curve_right_view_is_global'] = right_view_is_global
            state['curve_right_view_is_elastic'] = right_view_is_elastic
            curve_sections.append({
                'focus': 'curve_right',
                'metric_id': right_metric_id,
                'label': self._metric_label(right_metric_id),
                'view_is_global': right_view_is_global,
                'view_is_elastic': right_view_is_elastic,
                'compare_count': len(self._collect_compare_series(right_metric_id)),
            })
        state['curve_sections'] = curve_sections
        state['curve'] = curve
        state['curve_rows'] = curve_rows
        status_line_inline, status_line_fullscreen = self._build_status_lines(state)
        state['status_line'] = status_line_inline
        state['status_line_inline'] = status_line_inline
        state['status_line_fullscreen'] = status_line_fullscreen
        return state

    def _refresh_frame_state(self, base_state):
        return self._build_frame_state(base_state)

    def _render_last_state(self):
        if not self._last_frame_state:
            return
        state = self._refresh_frame_state(self._last_frame_state)
        self._last_frame_state = state
        if self.display_mode == 'fullscreen':
            if self._can_render_cached_fullscreen():
                self._render_fullscreen(state)
            return
        inline_state = dict(state)
        inline_state['epoch_display'] = None
        inline_state['epoch_summary_offset'] = len(self.epoch_summaries)
        self._render_inline(inline_state, wipe=False, flush=0)

    def _handle_key(self, key):
        down_key = key in ('j', '\x1b[B')
        up_key = key in ('k', '\x1b[A')
        if self.input_mode == 'path':
            if key in ('\x1b', '\x1b'):
                self.input_mode = None
                self.active_action = None
                self._render_last_state()
                return
            if key in ('\r', '\n'):
                self._execute_action(self.active_action, self.input_buffer)
                self._render_last_state()
                return
            if key == '\x7f':
                self.input_buffer = self.input_buffer[:-1]
            elif key.isprintable() and key not in ('\t',):
                self.input_buffer += key
            self._refresh_input_candidates()
            self._render_last_state()
            return

        if self.drawer_mode == 'browse':
            if key in ('\x1b', '\x1b'):
                self._clear_action_ui()
                self._render_last_state()
                return
            if key == 'p':
                seed = self.drawer_entries[0]['path'] if self.drawer_entries else self.drawer_target_path or self.drawer_path
                self._open_path_input(self.active_action, seed)
                self._render_last_state()
                return
            if down_key and self.drawer_entries:
                self.drawer_idx = (self.drawer_idx + 1) % len(self.drawer_entries)
                self._render_last_state()
                return
            if up_key and self.drawer_entries:
                self.drawer_idx = (self.drawer_idx - 1) % len(self.drawer_entries)
                self._render_last_state()
                return
            if key in ('\r', '\n') and self.drawer_entries:
                entry = self.drawer_entries[self.drawer_idx]
                if entry['kind'] == 'input':
                    self._open_path_input(self.active_action, entry['path'])
                elif entry['kind'] == 'select':
                    self._execute_action(self.active_action, entry['path'])
                else:
                    self.drawer_path = entry['path']
                    self.drawer_idx = 0
                    self._refresh_browse_entries()
                self._render_last_state()
                return

        if self.display_mode == 'fullscreen' and self.focused_panel == 'compare' and key in (' ', '\r', '\n'):
            self._toggle_selected_compare_history()
            self._render_last_state()
            return

        if self.action_palette_open:
            if key in ('\x1b', '\x1b'):
                self._clear_action_ui()
                self._render_last_state()
                return
            if down_key:
                self.action_idx = (self.action_idx + 1) % len(self.action_items)
                self._render_last_state()
                return
            if up_key:
                self.action_idx = (self.action_idx - 1) % len(self.action_items)
                self._render_last_state()
                return
            if key in ('\r', '\n'):
                action, _ = self.action_items[self.action_idx]
                self._start_browse_action(action)
                self._render_last_state()
                return

        key_lower = key.lower()
        if key_lower == ':':
            if self.display_mode != 'fullscreen' and self.review_mode and self._is_fullscreen_available():
                self._set_display_mode('fullscreen')
            if self.display_mode == 'fullscreen':
                self._open_action_palette()
                self._render_last_state()
            return
        if key_lower == 'q':
            if self.review_mode:
                self._exit_review = True
                if self.display_mode == 'fullscreen':
                    self._set_display_mode('inline')
                return
            return
        if key_lower == 's':
            if self.display_mode == 'fullscreen':
                self._clear_action_ui()
                self._set_display_mode('inline')
                self._push_event('Fullscreen hidden; inline output restored.')
                self._print_inline_notice('[TCurve fullscreen hidden, inline output restored]')
                self._render_last_state()
            elif self._is_fullscreen_available():
                self.fullscreen_warned = False
                self._set_display_mode('fullscreen')
                self._push_event('Fullscreen enabled.')
                self._render_last_state()
            elif not self.fullscreen_warned:
                self.fullscreen_warned = True
                self._push_event('Fullscreen unavailable in current terminal.')
                self._print_inline_notice('[TCurve] fullscreen unavailable in current terminal')
            return
        metric_ids = self._current_metric_ids(self._last_frame_state['items'] if self._last_frame_state is not None else None)
        curve_focus = self._current_curve_side()
        curve_focused = self.display_mode != 'fullscreen' or self.focused_panel in ('curve', 'curve_left', 'curve_right')
        if down_key:
            if self.display_mode == 'fullscreen' and self.focused_panel == 'epochs' and self.epoch_summaries:
                total_pages = max(1, (len(self.epoch_summaries) + 4) // 5)
                self.epoch_page = min(self.epoch_page + 1, total_pages - 1)
            elif self.display_mode == 'fullscreen' and self.focused_panel == 'compare' and self.compared_histories:
                self.compare_selection_idx = (self.compare_selection_idx + 1) % len(self.compared_histories)
            elif metric_ids and curve_focused:
                self.inline_manual_metric = True
                if curve_focus == 'right' and self.curve_split:
                    self.curve_right_metric_idx = (self.curve_right_metric_idx + 1) % len(metric_ids)
                else:
                    self.selected_metric_idx = (self.selected_metric_idx + 1) % len(metric_ids)
        elif up_key:
            if self.display_mode == 'fullscreen' and self.focused_panel == 'epochs' and self.epoch_summaries:
                self.epoch_page = max(self.epoch_page - 1, 0)
            elif self.display_mode == 'fullscreen' and self.focused_panel == 'compare' and self.compared_histories:
                self.compare_selection_idx = (self.compare_selection_idx - 1) % len(self.compared_histories)
            elif metric_ids and curve_focused:
                self.inline_manual_metric = True
                if curve_focus == 'right' and self.curve_split:
                    self.curve_right_metric_idx = (self.curve_right_metric_idx - 1) % len(metric_ids)
                else:
                    self.selected_metric_idx = (self.selected_metric_idx - 1) % len(metric_ids)
        elif key_lower == 'g':
            current_global, _ = self._current_view_flags_for_side(curve_focus, self._last_frame_state)
            if curve_focus == 'right' and self.curve_split:
                self.curve_right_view_global = not current_global
                target = 'right curve'
            else:
                self.is_global = not current_global
                target = 'left curve' if self.curve_split else 'curve'
            self._push_event('%s view toggled to %s.' % (target.title(), 'global' if (self.curve_right_view_global if curve_focus == 'right' and self.curve_split else self.is_global) else 'recent'))
        elif key_lower == 'e':
            _, current_elastic = self._current_view_flags_for_side(curve_focus, self._last_frame_state)
            if curve_focus == 'right' and self.curve_split:
                self.curve_right_view_elastic = not current_elastic
                target = 'right curve'
            else:
                self.is_elastic = not current_elastic
                target = 'left curve' if self.curve_split else 'curve'
            self._push_event('%s y-axis toggled to %s.' % (target.title(), 'elastic' if (self.curve_right_view_elastic if curve_focus == 'right' and self.curve_split else self.is_elastic) else 'fixed'))
        elif key_lower == 'v':
            self._toggle_curve_split()
        elif key_lower == 'r':
            if self.display_mode == 'fullscreen':
                self._toggle_resources()
            else:
                self.log_panel_visible = True
                self._push_event('Resource monitor is available in fullscreen mode.')
        elif key_lower == 'l':
            self.log_panel_visible = not self.log_panel_visible
            self._push_event('Event panel %s.' % ('shown' if self.log_panel_visible else 'hidden'))
        elif key_lower == 'i':
            self.image_panel_visible = not self.image_panel_visible
            self._push_event('Image panel %s.' % ('shown' if self.image_panel_visible else 'hidden'))
        elif key_lower == 't':
            if self.focused_panel in self._focus_order():
                pane_name = 'curve' if self.focused_panel in ('curve_left', 'curve_right') else self.focused_panel
                if pane_name in self.collapsed_panes:
                    self.collapsed_panes.remove(pane_name)
                    self._push_event('%s pane expanded.' % pane_name.title())
                else:
                    self.collapsed_panes.add(pane_name)
                    self._push_event('%s pane collapsed.' % pane_name.title())
        elif key_lower == '?':
            self.help_visible = not self.help_visible
        elif key == '\t':
            order = self._focus_order()
            focus_idx = order.index(self.focused_panel) if self.focused_panel in order else 0
            self.focused_panel = order[(focus_idx + 1) % len(order)]
            self._push_event('Focus moved to %s.' % self.focused_panel)
        else:
            return
        self._render_last_state()

    def _can_render_cached_fullscreen(self):
        required = {'stage', 'epoch', 'mile', 'known_mpe', 'mpe', 'items', 'status_line', 'view_is_global', 'view_is_elastic'}
        return self._last_frame_state is not None and required.issubset(self._last_frame_state.keys())

    def _decode_pending_keys(self, keys):
        decoded = []
        idx = 0
        while idx < len(keys):
            if idx + 2 < len(keys) and keys[idx] == '\x1b' and keys[idx + 1] == '[' and keys[idx + 2] in ('A', 'B'):
                decoded.append('\x1b[A' if keys[idx + 2] == 'A' else '\x1b[B')
                idx += 3
            else:
                decoded.append(keys[idx])
                idx += 1
        return decoded

    def _process_pending_input(self):
        for key in self._decode_pending_keys(self._drain_pending_keys()):
            self._handle_key(key)

    def _start_review_mode(self):
        self._clear_action_ui()
        self._ensure_input_listener()
        if self.char_image:
            self.collapsed_panes.add('image')
        self.review_mode = True
        self._exit_review = False
        self._push_event('Run finished. Press q to exit review mode.')
        self._print_inline_notice('[TCurve review mode active: press s to switch views, q to exit]')
        self._render_last_state()

    def finalize(self, review=True):
        try:
            if not self.show:
                return
            if self._last_frame_state is None:
                return
            if self.display_mode != 'fullscreen':
                self._clear_action_ui()
                return
            if not review or not self._is_interactive_terminal():
                self._clear_action_ui()
                return
            self._start_review_mode()
            while not self._exit_review:
                self._process_pending_input()
                time.sleep(0.05)
        finally:
            try:
                if self.display_mode == 'fullscreen':
                    self._set_display_mode('inline')
                self.review_mode = False
                self._exit_review = False
                self._finish_inline()
            finally:
                self._stop_input_listener()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.finalize(review=exc_type is None)
        return False

    def _formatAsStr(self, stage, abbr, value, epoch, mile, mpe):
        form, mode = self.metrics[abbr]
        if isinstance(form, str):
            form = '%-' + form
        if mode == RAW:
            return (' %%s ➭ \033[1;36m%s\033[0m |' % form) % (abbr, value)
        elif mode == PERCENT:
            return (' %%s ➭ \033[1;36m%s%%%%\033[0m |' % form) % (abbr, value*100)
        elif mode == INVIZ:
            form(value, epoch, mile, mpe, stage)
            return ''
        elif mode == IMAGE:
            if form(value, epoch, mile, mpe, stage):
                assert isinstance(value, np.ndarray), 'TCURVE ERROR ៙ the image must be an numpy array.'
                H, W = value.shape
                assert W<=128, 'TCURVE ERROR ៙ the image width should not be greater than 128.'
                assert H<=96, 'TCURVE ERROR ៙ the image height should not be greater than 64.'
                if value.dtype in (np.float16, np.float32):
                    assert value.min()>=0 and value.max()<=1, 'TCURVE ERROR ៙ the pixels in float point should not be out of [0,1].'
                elif value.dtype == np.uint8:
                    value = (value.astype(np.float32)) / 255.
                else:
                    raise TypeError('TCURVE ERROR ៙ the image dtype must be one of fp16, fp32 and uint8.')
                self.char_image = ''
                self.image_row = 1
                for y in range(0,H,2):
                    for x in range(W):
                        self.char_image += self.char_pixel[round(float(value[y, x]) * (len(self.char_pixel)-1))]
                    self.char_image += max(0, 128 - W) * ' ' + '\n'
                    self.image_row += 1
            return ''
        elif mode == CUSTOM:
            string = form(value, epoch, mile, mpe, stage)
            return ' %s ➭ \033[1;36m%s\033[0m |' % (abbr, string)
        else:
            raise KeyError('TCURVE ERROR ៙ the display mode is an illegal metrics option.')

    def __iter__(self):
        return self

    def __next__(self):
        try:
            ret = self.iterable.__next__()
            entry = self._make_entry(ret)
            call_kwargs = dict(self.wrapper_kwargs)
            call_kwargs.pop('entry_fn', None)
            epoch = call_kwargs.pop('epoch', 0)
            stage = call_kwargs.pop('stage', 'ITER')
            call_kwargs.pop('mpe', None)
            self(entry, epoch, self.cnt, self.length, stage, **call_kwargs)
            self.cnt += 1
            return ret
        except StopIteration:
            self.finalize(review=True)
            raise StopIteration

    def __call__(self, entry, epoch, mile, mpe, stage='ITER', interv=1, duration=None, plot=True, wipe=False, flush=0,
                is_global=True, is_elastic=False, in_loop=(-1,), last_for=1):
        if not self.show:
            return
        self._ensure_input_listener()
        self._process_pending_input()
        assert not (plot and wipe), 'TCURVE ERROR ៙ "plot" and "wipe" are mutually exclusive.'
        known_mpe = mpe is not None and mpe > 0
        epoch += 1
        mile += 1
        string_mile = ''
        string_epoch = ''
        flag_display = False
        flag_epoch_end = False
        epoch_visible_count = 0
        len_loop = len(in_loop)
        assert in_loop[0] < 0 or len_loop > 1, 'TCURVE ERROR ៙ the dashboard should loop through more than one curve.'
        if mile % interv == 0:
            flag_display = True
        if known_mpe and mile % mpe == 0:
            flag_epoch_end = True
            if epoch > self.max_epoch:
                self.max_epoch = epoch
        if self.first_call:
            self.time = time.time()
            self.first_call = False
        items = []
        for abbr, value in entry.items():
            if flag_display or self.metrics[abbr][1] == INVIZ:
                string_mile += self._formatAsStr(stage, abbr, value, epoch, mile, mpe)
            if self.log_dir is None or self.metrics[abbr][1] in (IMAGE, INVIZ, CUSTOM):
                if flag_epoch_end:
                    _ = self._formatAsStr(stage, abbr, value, epoch, -1, mpe)
                continue
            global_mile = ((epoch - 1) * mpe + mile) if known_mpe else mile
            metric_id = self._metric_id(stage, abbr)
            items.append(metric_id)
            self._ensure_metric_storage(metric_id)
            if isinstance(value, np.ndarray) and value.dtype == np.float16:
                value = value.astype(np.float32)
            self.win_mile[metric_id][(global_mile - 1) % self.window] = value
            if known_mpe:
                if len(self.gauge_epoch[metric_id]) == len(self.trail_epoch[metric_id]):
                    self.gauge_epoch[metric_id].append(0.0)
                self.gauge_epoch[metric_id][-1] += value
            if global_mile < self.window:
                gauge = np.array(self.win_mile[metric_id][:global_mile]).mean()
            else:
                gauge = np.array(self.win_mile[metric_id]).mean()
            self.gauge_mile[metric_id].append(gauge)
            if len(self.trail_mile[metric_id]) < len(self.gauge_mile[metric_id]):
                self.trail_mile[metric_id].append(global_mile)
            if flag_epoch_end:
                self.gauge_epoch[metric_id][-1] /= mpe
                if len(self.trail_epoch[metric_id]) < len(self.gauge_epoch[metric_id]):
                    self.trail_epoch[metric_id].append(epoch)
                indicator = self._formatAsStr(stage, abbr, self.gauge_epoch[metric_id][-1], epoch, -1, mpe)
                string_epoch += indicator
                if indicator != '':
                    epoch_visible_count += 1

        metric_ids = self._current_metric_ids(items)
        if self.display_mode == 'fullscreen':
            _ = self._select_fullscreen_metric(items)
        elif flag_display and len(self.gauge_mile) > 0 and len(entry) > 0 and plot:
            _ = self._select_inline_metric(items, mile, interv, in_loop, last_for)

        ordinal = self._get_ordinal(epoch)
        if duration is None:
            if self.prev_time < 0:
                duration = '--:--'
                self.prev_time = time.time()
            else:
                curr_time = time.time()
                duration = '%.3f' % (curr_time - self.prev_time)
                self.prev_time = curr_time
        else:
            duration = '%.3f' % duration
        epoch_display = None
        epoch_summary_offset = len(self.epoch_summaries)
        if flag_epoch_end:
            mileage = str(epoch * mpe)
            epoch_display = '| %d%s Epoch ⚘ %s Miles ₪ %.2fs/epoch | %s |%s' % (
                epoch,
                ordinal,
                mileage,
                (time.time() - self.time),
                stage,
                string_epoch,
            )
            self.epoch_summaries.append(epoch_display)
            self.epoch_page = 0
            epoch_summary_offset = len(self.epoch_summaries) - 1
            self.time = time.time()

        raw_state = {
            'epoch': epoch,
            'mile': mile,
            'mpe': mpe,
            'known_mpe': known_mpe,
            'stage': stage,
            'items': items,
            'string_mile': string_mile,
            'duration': duration,
            'ordinal': ordinal,
            'interv': interv,
            'epoch_display': epoch_display,
            'epoch_visible_count': epoch_visible_count,
            'epoch_summary_offset': epoch_summary_offset,
            'plot': plot,
            'default_view_is_global': is_global,
            'default_view_is_elastic': is_elastic,
        }
        state = self._build_frame_state(raw_state)
        self._last_frame_state = state
        if self.display_mode == 'fullscreen':
            if flag_display or flag_epoch_end:
                self._render_fullscreen(state)
        else:
            if flag_display:
                self._render_inline(state, wipe=wipe, flush=flush)
            elif flag_epoch_end:
                self._render_inline(state, wipe=wipe, flush=flush)

    def read(self, entry, stage, epoch=-1):
        if not self.show:
            return 0
        assert epoch!=0, 'TCURVE ERROR ៙ epoch starts from 1.'
        epoch = epoch-1 if epoch>0 else epoch
        return self.gauge_epoch[self._metric_id(stage, entry)][epoch]

    def record(self, entry, stage, value):
        if not self.show:
            return
        metric_id = self._metric_id(stage, entry)
        if metric_id in self.gauge_epoch.keys():
            raise KeyError('TCURVE ERROR ៙ %s has been taken in dashboard.' % self._metric_label(metric_id))
        else:
            self.gauge_epoch[metric_id] = value

    def _argm(self, arr):
        m = [arr[0], arr[0]] # min, max
        idx = [0, 0]
        for i, a in enumerate(arr):
            if a < m[0]:
                m[0] = a
                idx[0] = i
            if a > m[1]:
                m[1] = a
                idx[1] = i
        idx[0] += 1
        idx[1] += 1
        return m + idx

    def _aligned_series(self, unit, metric_id):
        if unit == 'mile':
            trail = self.trail_mile[metric_id]
            gauge = self.gauge_mile[metric_id]
        elif unit == 'epoch':
            trail = self.trail_epoch[metric_id]
            gauge = self.gauge_epoch[metric_id]
        else:
            raise ValueError('TCURVE ERROR ៙ unsupported series unit %s.' % unit)
        length = min(len(trail), len(gauge))
        if length == 0:
            return [], []
        if len(trail) != len(gauge):
            self._push_event(
                'Length mismatch in %s series for %s; truncated to %d points.' %
                (unit, self._metric_label(metric_id), length)
            )
        return trail[:length], gauge[:length]

    def _is_scalar_metric(self, metric_id):
        entry = metric_id[1]
        if self.metrics is None or entry not in self.metrics:
            return True
        return self.metrics[entry][1] in (RAW, PERCENT)

    def _select_plot_metric_ids(self, select):
        metric_ids = [metric_id for metric_id in sorted(self.gauge_mile.keys()) if self._is_scalar_metric(metric_id)]
        if select is None:
            return metric_ids
        selected = []
        available = set(metric_ids)
        known = set(self.gauge_mile.keys())
        for metric_id in select:
            parsed = self._parse_metric_label(metric_id)
            if parsed not in known:
                raise ValueError('TCURVE ERROR ៙ selected curve %s has no mile series.' % self._metric_label(parsed))
            if parsed not in available:
                raise ValueError('TCURVE ERROR ៙ selected curve %s is not a scalar metric and cannot be plotted.' % self._metric_label(parsed))
            selected.append(parsed)
        return selected

    def _plot_group_key(self, metric_id, group_by):
        stage, metric = metric_id
        if group_by == SERIES:
            return metric_id
        if group_by == METRIC:
            return metric
        if group_by == STAGE:
            return stage
        if group_by == NOTHING:
            return 'all'
        raise ValueError('TCURVE ERROR ៙ "group_by" must be SERIES, METRIC, STAGE, or NOTHING.')

    def _plot_group_token(self, group_key):
        if isinstance(group_key, tuple):
            return '%s_%s' % (self._metric_token(group_key[1]), self._metric_token(group_key[0]))
        return self._metric_token(group_key)

    def prepend_history(self, history):
        history = os.path.abspath(os.path.expanduser(history))
        series = self._read_history_dir(history)
        for raw_metric_id, payload in series.items():
            metric_id = self._resolve_history_metric_id(raw_metric_id) or raw_metric_id
            self._ensure_metric_storage(metric_id)
            for unit, (trail_values, gauge_values) in payload.items():
                if not gauge_values:
                    continue
                if unit == 'mile':
                    self.trail_mile[metric_id] = (np.asarray(trail_values) - trail_values[-1]).tolist() + self.trail_mile[metric_id]
                    self.gauge_mile[metric_id] = list(gauge_values) + self.gauge_mile[metric_id]
                elif unit == 'epoch':
                    self.trail_epoch[metric_id] = (np.asarray(trail_values) - trail_values[-1]).tolist() + self.trail_epoch[metric_id]
                    self.gauge_epoch[metric_id] = list(gauge_values) + self.gauge_epoch[metric_id]
                else:
                    raise ValueError('TCURVE ERROR ៙ header is either to be "mile" or "epoch", but got %s.' % unit)

    def compare_history(self, history):
        history = os.path.abspath(os.path.expanduser(history))
        series = self._read_history_dir(history)
        compared = {'path': history, 'label': os.path.basename(history.rstrip(os.sep)) or history, 'mile': {}, 'epoch': {}}
        matched = 0
        seen = set()
        for raw_metric_id, payload in series.items():
            metric_id = self._resolve_history_metric_id(raw_metric_id, include_metrics=True)
            if metric_id is None:
                continue
            if metric_id[1] != raw_metric_id[1]:
                continue
            if 'mile' in payload:
                compared['mile'][metric_id] = payload['mile']
                seen.add(metric_id)
            if 'epoch' in payload:
                compared['epoch'][metric_id] = payload['epoch']
                seen.add(metric_id)
        matched = len(seen)
        if matched == 0:
            raise ValueError('TCURVE ERROR ៙ no comparable metrics were found in %s.' % history)
        compared['enabled'] = True
        self.compared_histories = [item for item in self.compared_histories if item['path'] != history]
        self.compared_histories.append(compared)
        self.compare_selection_idx = min(self.compare_selection_idx, max(0, len(self.compared_histories) - 1))
        return matched

    def load_history(self, history):
        self.prepend_history(history)


    def export_csv(self, subdir='', base_path=None):
        _, pd, _ = _import_logging_deps()
        log_dir = self._resolve_log_dir(subdir, base_path=base_path)
        for metric_id in self.gauge_mile.keys():
            stage, metric = metric_id
            label = self._metric_label(metric_id)
            metric_token = self._metric_token(metric)
            stage_token = self._metric_token(stage)
            mile_x, mile_y = self._aligned_series('mile', metric_id)
            if mile_y:
                df = pd.DataFrame(data={'mile': mile_x, label: mile_y})
                df.to_csv(os.path.join(log_dir, '%s_%s_mile.csv' % (metric_token, stage_token)), index=None)
            epoch_x, epoch_y = self._aligned_series('epoch', metric_id)
            if epoch_y:
                df = pd.DataFrame(data={'epoch': epoch_x, label: epoch_y})
                df.to_csv(os.path.join(log_dir, '%s_%s_epoch.csv' % (metric_token, stage_token)), index=None)

    def plot_curves(self, subdir='', base_path=None, select=None, group_by=METRIC):
        log_dir = self._resolve_log_dir(subdir, base_path=base_path)
        boards = {}
        for metric_id in self._select_plot_metric_ids(select):
            boards.setdefault(self._plot_group_key(metric_id, group_by), []).append(metric_id)
        if not boards:
            return
        plt, pd, sns = _import_logging_deps()
        sns.set_theme()
        for group_key, metric_ids in boards.items():
            fig = plt.figure()
            ax = fig.add_subplot(111)
            plotted = False
            mile_tail = 0
            last_value = 0
            for metric_id in metric_ids:
                mile_x, mile_y = self._aligned_series('mile', metric_id)
                if not mile_y:
                    continue
                entry = metric_id[1]
                ymin, ymax, xmin, xmax = self._argm(mile_y)
                xoff = max(len(mile_x), 1) * 0.02
                yoff = (ymax - ymin) * 0.02
                x_min = mile_x[xmin - 1]
                x_max = mile_x[xmax - 1]
                ax.annotate(self._format_logged_value(entry, ymin), (x_min - xoff, ymin + yoff))
                ax.annotate(self._format_logged_value(entry, ymax), (x_max - xoff, ymax + yoff))
                data = pd.DataFrame({self._metric_label(metric_id): mile_y}, index=mile_x)
                sns.lineplot(data=data, markers=False, ax=ax)
                plotted = True
                mile_tail = max(mile_tail, mile_x[-1])
                last_value = mile_y[-1]
            if plotted:
                plt.savefig(os.path.join(
                    log_dir,
                    '%s_%.3g_mile_%d.jpg' % (self._plot_group_token(group_key), last_value, mile_tail),
                ))
            plt.close()

        for group_key, metric_ids in boards.items():
            fig = plt.figure()
            ax = fig.add_subplot(111)
            plotted = False
            epoch_tail = 0
            for metric_id in metric_ids:
                epoch_x, epoch_y = self._aligned_series('epoch', metric_id)
                if not epoch_y:
                    continue
                ymin, ymax, xmin, xmax = self._argm(epoch_y)
                xoff = max(len(epoch_x), 1) * 0.02
                yoff = (ymax - ymin) * 0.02
                x_min = epoch_x[xmin - 1]
                x_max = epoch_x[xmax - 1]
                entry = metric_id[1]
                ax.annotate(self._format_logged_value(entry, ymin), (x_min - xoff, ymin + yoff))
                ax.annotate(self._format_logged_value(entry, ymax), (x_max - xoff, ymax + yoff))
                data = pd.DataFrame({self._metric_label(metric_id): np.asarray(epoch_y)}, index=epoch_x)
                sns.lineplot(data=data, markers=True, ax=ax)
                plotted = True
                epoch_tail = max(epoch_tail, epoch_x[-1])
            if plotted:
                plt.savefig(os.path.join(log_dir, '%s_epoch_%d.jpg' % (self._plot_group_token(group_key), max(self.max_epoch, epoch_tail))))
            plt.close()

    def log(self, subdir=''):
        if not self.show:
            return
        self.plot_curves(subdir=subdir)
        self.export_csv(subdir=subdir)


if __name__ == "__main__": # for simple tests
    from random import random
    # print('-'*34)
    # print('|      ▽ a simple wrapper ▽      |')
    # print('-'*34 + '\n')
    # # a simple wrapper
    # for i in Dash(range(20)):
    #     time.sleep(0.2)
    # time.sleep(1)
    # # wrap a generator
    # for i in Dash(enumerate(range(30))):
    #     time.sleep(0.2)

    # # with keyword arguments
    # for i, n in Dash(
    #     enumerate(range(30)),
    #     metrics={'number': ['d', RAW]},
    #     entry_fn=lambda index, item: {'number': item[1]},
    #     epoch=2,
    #     mpe=30,
    #     stage='COUNT',
    #     interv=1,
    #     wipe=False,
    # ):
    #     time.sleep(0.2)

    # in a complicated manner
    unit_acc = [0.012, 0.045, 0.134, 0.189, 0.234, 0.278, 0.345, 0.378, 0.456, 0.423, 0.51, 0.599, 0.623, 0.62, 0.7]
    fake_acc = unit_acc + unit_acc[::-1] + unit_acc + unit_acc[::-1] + unit_acc + unit_acc[::-1]
    fake_acc = [fa+0.1 for fa in fake_acc] + [fa*2.1 for fa in fake_acc] + [fa*3-0.2 for fa in fake_acc]
    fake_loss = len(fake_acc) * [0.1]

    gray_frames = []
    gray_dir = os.path.join(os.getcwd(), 'unit_tests', 'gray_imgs')
    if os.path.isdir(gray_dir):
        try:
            from PIL import Image
            gray_paths = [
                os.path.join(gray_dir, name)
                for name in sorted(os.listdir(gray_dir))
                if name.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp'))
            ]
            gray_frames = [
                np.asarray(Image.open(img_path).convert('L'), dtype=np.float32) / 255.0
                for img_path in gray_paths[:10]
            ]
        except Exception:
            gray_frames = []

    demo_metric = {'Acc': ['.1f', PERCENT], 'Loss': ['.2f', RAW], 'MNIST': [lambda *info: True, IMAGE]}
    
    with Dash(metrics=demo_metric, divisor=15, resources=True) as tcd:
        for ep in range(3):
            for i, a in enumerate(fake_acc):
                time.sleep(0.1)
                entry = {'Acc': a + random()/10, 'Loss': fake_loss[i] + random()/5}
                if gray_frames:
                    entry['MNIST'] = gray_frames[(ep * len(fake_acc) + i//4) % len(gray_frames)]
                tcd(entry, ep, i, len(fake_acc))
