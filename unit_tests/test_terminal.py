import io
import os
import select
import signal
import subprocess
import sys
import unittest
import warnings
from contextlib import contextmanager
from unittest import mock

import tcurve as tc
from tcurve import dash as dash_module

try:
    import pty
    import termios
except ImportError:
    pty = termios = None


@unittest.skipUnless(pty is not None and dash_module.fcntl is not None, 'requires POSIX terminals')
class TerminalOwnershipTests(unittest.TestCase):
    @contextmanager
    def terminal(self):
        master, slave = pty.openpty()
        with os.fdopen(os.dup(slave), 'r') as input_stream, \
                os.fdopen(os.dup(slave), 'w', buffering=1) as output_stream:
            try:
                with mock.patch.object(sys, 'stdin', input_stream), \
                        mock.patch.object(sys, 'stdout', output_stream):
                    yield master, slave
            finally:
                os.close(master)
                os.close(slave)

    def probe(self, slave, fail=False):
        script = '''
import os, sys
import tcurve as tc
sys.stdin = os.fdopen(os.dup(int(sys.argv[1])), 'r')
sys.stdout = os.fdopen(os.dup(int(sys.argv[1])), 'w')
dash = tc.Dash()
try:
    dash._acquire_terminal()
except RuntimeError:
    sys.__stdout__.write('occupied')
else:
    sys.__stdout__.write('acquired')
    sys.__stdout__.flush()
    if sys.argv[2] == 'fail':
        raise RuntimeError('unexpected exit')
    dash.finalize(review=False)
'''
        return subprocess.run(
            [sys.executable, '-c', script, str(slave), 'fail' if fail else 'normal'],
            pass_fds=(slave,), capture_output=True, text=True, timeout=10,
        )

    def test_second_instance_fails_before_input_mode_or_output_changes(self):
        with self.terminal() as (master, slave):
            first, second = tc.Dash(), tc.Dash()
            try:
                first._ensure_input_listener()
                attrs = termios.tcgetattr(slave)
                with self.assertRaisesRegex(RuntimeError, 'already occupied'):
                    second._ensure_input_listener()
                self.assertEqual(termios.tcgetattr(slave), attrs)
                self.assertFalse(second._input_listener_started)
                self.assertFalse(select.select([master], [], [], 0)[0])
            finally:
                first.finalize(review=False)
                second.finalize(review=False)

    def test_finalize_restores_input_before_allowing_next_instance(self):
        with self.terminal() as (_, slave):
            original = termios.tcgetattr(slave)
            first, second = tc.Dash(), tc.Dash()
            first._ensure_input_listener()
            first.finalize(review=False)
            first.finalize(review=False)
            self.assertEqual(termios.tcgetattr(slave), original)
            try:
                second._ensure_input_listener()
            finally:
                second.finalize(review=False)

    def test_other_process_is_blocked_until_finalize(self):
        with self.terminal() as (_, slave):
            dash = tc.Dash()
            try:
                dash._acquire_terminal()
                self.assertEqual(self.probe(slave).stdout, 'occupied')
            finally:
                dash.finalize(review=False)
            self.assertEqual(self.probe(slave).stdout, 'acquired')

    def test_finalize_failure_still_releases_terminal(self):
        with self.terminal() as (_, slave):
            dash = tc.Dash()
            dash._acquire_terminal()
            dash._last_frame_state = {}
            with mock.patch.object(dash, '_finish_inline', side_effect=RuntimeError('cleanup failed')):
                with self.assertRaisesRegex(RuntimeError, 'cleanup failed'):
                    dash.finalize(review=False)
            self.assertIsNone(dash._terminal_lock_fd)
            self.assertEqual(self.probe(slave).stdout, 'acquired')

    def test_different_terminals_can_be_used_at_once(self):
        with self.terminal():
            dash = tc.Dash()
            dash._acquire_terminal()
            try:
                with self.terminal() as (_, slave):
                    self.assertEqual(self.probe(slave).stdout, 'acquired')
            finally:
                dash.finalize(review=False)

    def test_process_exception_releases_lock(self):
        with self.terminal() as (_, slave):
            result = self.probe(slave, fail=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, 'acquired')
            self.assertEqual(self.probe(slave).stdout, 'acquired')

    def test_redirected_stdout_does_not_acquire_lock_or_listen(self):
        with self.terminal():
            with mock.patch.object(sys, 'stdout', io.StringIO()):
                dash = tc.Dash()
                dash._ensure_input_listener()
                self.assertIsNone(dash._terminal_lock_fd)
                self.assertFalse(dash._input_listener_started)

    def test_terminal_output_is_protected_without_interactive_stdin(self):
        with self.terminal():
            with mock.patch.object(sys, 'stdin', io.StringIO()):
                first, second = tc.Dash(), tc.Dash()
                try:
                    first._ensure_input_listener()
                    self.assertIsNotNone(first._terminal_lock_fd)
                    self.assertFalse(first._input_listener_started)
                    with self.assertRaisesRegex(RuntimeError, 'already occupied'):
                        second._ensure_input_listener()
                finally:
                    first.finalize(review=False)
                    second.finalize(review=False)

    def test_force_killed_process_releases_lock(self):
        with self.terminal() as (_, slave):
            script = '''
import os, signal, sys
import tcurve as tc
sys.stdout = os.fdopen(os.dup(int(sys.argv[1])), 'w')
dash = tc.Dash()
dash._acquire_terminal()
sys.__stdout__.write('ready\\n')
sys.__stdout__.flush()
signal.pause()
'''
            process = subprocess.Popen(
                [sys.executable, '-c', script, str(slave)], pass_fds=(slave,),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                self.assertTrue(select.select([process.stdout], [], [], 10)[0])
                self.assertEqual(process.stdout.readline(), 'ready\n')
                self.assertEqual(self.probe(slave).stdout, 'occupied')
                process.send_signal(signal.SIGKILL)
                process.communicate(timeout=10)
                self.assertEqual(self.probe(slave).stdout, 'acquired')
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=10)

    @unittest.skipUnless(hasattr(os, 'fork'), 'requires fork')
    def test_fork_child_cannot_use_or_restore_inherited_dash(self):
        with self.terminal() as (_, slave):
            dash = tc.Dash()
            original = termios.tcgetattr(slave)
            dash._acquire_terminal()
            dash._stdin_fd = slave
            dash._stdin_attrs = original
            tty_attrs = termios.tcgetattr(slave)
            tty_attrs[3] &= ~termios.ECHO
            termios.tcsetattr(slave, termios.TCSANOW, tty_attrs)
            read_fd, write_fd = os.pipe()
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', category=DeprecationWarning, message='This process .* is multi-threaded')
                pid = os.fork()
            if pid == 0:
                os.close(read_fd)
                try:
                    try:
                        dash._ensure_input_listener()
                    except RuntimeError:
                        rejected = True
                    else:
                        rejected = False
                    dash._restore_input_mode()
                    dash.finalize(review=False)
                    safe = (rejected and dash._terminal_lock_fd is None and
                            termios.tcgetattr(slave) == tty_attrs)
                    os.write(write_fd, b'yes' if safe else b'no')
                finally:
                    os._exit(0)
            os.close(write_fd)
            try:
                ready = bool(select.select([read_fd], [], [], 10)[0])
                if not ready:
                    os.kill(pid, signal.SIGKILL)
                self.assertTrue(ready)
                self.assertEqual(os.read(read_fd, 3), b'yes')
                self.assertEqual(self.probe(slave).stdout, 'occupied')
            finally:
                os.close(read_fd)
                os.waitpid(pid, 0)
                dash.finalize(review=False)
            self.assertEqual(termios.tcgetattr(slave), original)


if __name__ == '__main__':
    unittest.main()
