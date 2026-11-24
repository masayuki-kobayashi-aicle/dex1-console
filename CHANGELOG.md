# Changelog

## Unreleased

- Fix: `dex1 gui --no-log` was accepted but ignored, and the GUI always wrote a JSONL log. It now writes none (the log view and
  the Save button still work). Found after 0.1.0, which has this bug.
- Rerun export: the `rerun` extra is now `rerun-sdk==0.43.2` (was 0.37.1). Rerun 0.43 rewrites an application id that contains
  `.`, `|` or `+` and warns, so `export-rerun` now uses a safe id (`.|+` become `-`) and shows `--label` as the recording name.
  Checked with `rerun rrd verify` and a mock log, with and without `--video`; not checked by looking at the Viewer.
- CI installs the `rerun` extra and has an export test, so a Rerun bump is now tested.

## 0.1.0 (2026-11-23, pre-release)

- GUI: English / Japanese switch; position, speed and strength sliders; motor id at connect; auto zero (close until the finger
  stops, call that 0; session only; console `z`); raw torque; a log grouped by job with colours, a filter and a Save button.
- GUI layout: connection, live hand state and STOP sit in a top band that stays in view; Setup (preflight, auto zero) and Move are below, the log beside them. The preflight card lists what the five steps do (folded once it has passed), and the visual-check dialog explains what the step did and what yes / no mean.
- Speed (peak rad/s) can be requested instead of a time. Strength (position gain, 10-100 %) can be set per move.
- The preflight has five stages: the hand closes itself for the calibration and the operator only checks by eye that it is closed; the safety question was removed, and so was the confirmation before auto zero.
- `dex1 gui`: local web GUI (standard library only): buttons, live log view, preflight dialogs, STOP; loopback only, per-run token.
- First version: protocol, ESP-Prog transport, mock hand, controller with safety checks, preflight, console, JSONL log, Rerun export.
