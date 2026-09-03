# Changelog

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
