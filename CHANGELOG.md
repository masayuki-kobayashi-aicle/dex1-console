# Changelog

## 0.1.0 (2026-11-23, pre-release)

- GUI: English / Japanese switch; position, speed and strength sliders; motor id at connect; auto zero (close until the finger
  stops, call that 0; session only; console `z`); raw torque; a log grouped by job with colours, a filter and a Save button.
- GUI layout: connection, live hand state and STOP sit in a top band that stays in view; Setup (preflight, auto zero) and Move are below, the log beside them. The preflight card lists what the five steps do (folded once it has passed), and the visual-check dialog explains what the step did and what yes / no mean.
- Speed (peak rad/s) can be requested instead of a time. Strength (position gain, 10-100 %) can be set per move.
- The preflight has five stages: the hand closes itself for the calibration and the operator only checks by eye that it is closed; the safety question was removed, and so was the confirmation before auto zero.
- `dex1 gui`: local web GUI (standard library only): buttons, live log view, preflight dialogs, STOP; loopback only, per-run token.
- First version: protocol, ESP-Prog transport, mock hand, controller with safety checks, preflight, console, JSONL log, Rerun export.
