# Changelog

## 0.3.0

- Add `refresh_interv`, defaulting to 0.1 seconds, alongside the existing step interval. When both are positive, both conditions must pass; disabling both raises an error.
- Refresh immediately on the first frame, stage or epoch changes, epoch completion, user interaction, and finalization with pending data.
- Preserve per-call statistics, callback execution under the step rule, and per-step timing while skipping unnecessary frame construction and resource sampling.
- Rotate inline metrics by displayed updates rather than step numbers.
- Add POSIX terminal ownership protection across Dash instances and processes, held until finalization or process exit.
- Reject fork-inherited Dash instances in child processes and prevent child cleanup from restoring the parent's terminal state.
- Automatically use plain-text completion summaries for non-TTY output, without ANSI sequences, repeated frames, or terminal-width clipping.
- Report partial epoch summaries promptly and print the final progress once for unknown-length runs.
- Use independent Matplotlib Agg canvases for headless image export without switching the application's backend or closing its figures.
- Document refresh controls, multiprocessing, non-TTY output, and finalization for both inline and fullscreen modes.

## 0.2.6

- Compute epoch averages from each metric's actual sample count, including unfinished epochs.
- Add idempotent `end_epoch(stage=...)` and close unfinished epochs when the same stage starts a new epoch or the dashboard is finalized.
- Mark early epoch summaries as partial and keep statistics independent across stages.
- Fix rolling averages after early epoch termination and for intermittently reported metrics.
- Show inline epoch summaries above the current curve, image, view controls, and progress line.
- Document early epoch termination and the updated inline layout.

## 0.2.5

- Clear stale inline content when a shorter frame replaces a taller frame.
- Keep inline frames within the terminal height by limiting epoch summaries and image rows.
- Fit every inline output line to the terminal width to prevent unintended wrapping.
- Route dashboard content and terminal control sequences through the current output stream.

## 0.2.4

- Move inline view state above the progress line and label each control with its shortcut key.

## 0.2.3

- Stop the keyboard listener and restore terminal input mode during finalization.
- Restore the normal terminal screen when fullscreen review is interrupted.
- Document terminal recovery after a force-killed process.

## 0.2.2

- Fix inline finalization so subsequent terminal output does not overwrite epoch summaries.
- Ensure `finalize(review=False)` exits fullscreen immediately and still restores terminal output state.
- Document fullscreen review mode and the `review` option of `finalize()`.
- Refresh the package banner and remove its invalid escape sequence warning.
- Fix package discovery and include the build metadata and changelog in source distributions.

## 0.2.1

- Add flexible plot export with `select` and `group_by`, using `SERIES`, `METRIC`, `STAGE`, and `NOTHING`.
- Add `log(subdir=...)` as a shortcut for saving curve plots and CSV files.
- Add `prepend_history` and `compare_history` for loading previous CSV exports.
- Improve fullscreen split view controls for comparing two metrics.
- Improve fullscreen resource monitoring display with CPU, memory, GPU utilization, GPU temperature, and VRAM bars.
- Improve inline epoch summary rendering so previous epoch summaries remain visible.
- Validate terminal bounds for `span` and `divisor`, and block split view when `span` is too wide.
- Add up/down arrow key support for navigation.
- Document fullscreen controls, resource monitoring, history loading, plot export, and local tests.

## 0.2.0

- Rename the metric configuration argument from `format` to `metrics`.
- Rename the log directory argument from `log_way` to `log_dir`.
- Add `Dash` context manager support for manual dashboard runs.
- Add up/down arrow key support for navigation.
- Add terminal bounds checks for `span` and `divisor`, and block split view when `span` is too wide.
- Add opt-in fullscreen resource monitoring for CPU, memory, and NVIDIA GPU usage.
- Document fullscreen controls, history comparison, CSV export, plot export, and local tests.
- Keep error messages under the `TCURVE ERROR` prefix.
- Keep unit test output quiet during fullscreen rendering tests.

## 0.1.3

- Make plot drawing more flexible.

## 0.1.2

- Add macro variable documentation.

## 0.1.1

- Update the library icon.

## 0.1.0

- Update README.

## 0.0.4

- Fix an inner file bug.

## 0.0.3

- Fix an import bug.

## 0.0.2

- Add README.

## 0.0.1

- Publish the initial standalone package.
