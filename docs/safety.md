# Safety

The hand can pinch and break things. Keep fingers clear, keep a hand on the power, and run `dex1 preflight` first.

## Defaults (examples/dex1.toml)

| Limit | Value | Meaning |
|---|---|---|
| position_min_rad / open_limit_rad | -0.2 / 5.2 | targets outside are refused before anything is sent |
| closed_target_rad / open_target_rad | 0.1 / 5.1 | the closed target stays off the stop; no pressing |
| max_track_err_rad | 0.6 | abort when the hand is this far from the command |
| max_temp_c | 60 | abort above this case/coil temperature |
| max_missed_replies | 3 | abort after this many silent frames in a row |
| max_speed_rad_s | 1.5 | peak speed of the cosine ramp; shorter times are stretched |

Every move ends with a brake, also after Ctrl-C and after any error.

## Strength, speed and auto zero

| Item | Rule |
|---|---|
| Speed (rad/s) | the peak speed of the cosine ramp; above `max_speed_rad_s` it is refused, not silently clamped; time and speed together are refused |
| Strength (%) | position gain as a share of `kp_raw`, 10-100 %; **not a torque** (the unit of the reply's torque field is not known) |
| Auto zero | starts without a question (you check by eye afterwards; Stop brakes at once); closes at `zero_speed_rad_s` with the target at most `zero_lead_rad` ahead of the finger, so the push on the stop stays bounded; gain `zero_kp_raw`; stops when the position moves less than `zero_stall_move_rad` for `zero_stall_s`; refuses a stop more than `zero_tolerance_rad` from `expected_closed_rad` when the hand started in range; always brakes; keeps the old zero on failure |
| The zero offset | software only, this session only: not written to the hand. Moves need a new preflight after it changes |

All `zero_*` values are choices, not measurements on the hand. Stall detection uses position only, so a finger that is
blocked by an object looks the same as the closed stop; the confirmation question asks the operator to check.


## What was measured, and what was not

Measured on one right hand (id 7): closed stop about -0.06 rad, fully open about 5.35 rad, 5.0 rad stroke with no
missed replies, 33/29 C at 24.5 V.

Not verified: auto zero, strength and speed on a real hand (mock only), what the strength means in torque, the unit of the torque field, the left hand, other ids, other firmware, long or repeated runs (thermal), macOS. Calibration tolerance
is loose (+-0.2 rad). The mock's motion model is a simple first-order lag and says nothing about real dynamics.
