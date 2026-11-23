# Protocol

Frames are little-endian. The layouts follow Unitree's published SDK (BSD 3-Clause; see ../NOTICE). Checked against four frames
produced by the vendor library (`dex1 selftest`).

Command frame, 20 bytes: `fe ee`, `id | status<<4 | timeout<<7`, reserved, torque i16, speed i16, position i32,
k_pos u16, k_spd u16, CRC32 (u32). Status 0 = brake (lock), 1 = FOC.

Reply frame, 26 bytes. The CRC byte range of the reply is ambiguous; the decoder accepts three variants and reports
which matched.

Position scaling (measured by calling the vendor library): gear ratio 25, 32768 counts per rotor revolution,
`pos_raw = int(q_out * 25 * 32768 / 2pi)` (truncated toward zero). Gains: kp 5 -> k_pos 102, kd 0.05 -> k_spd 1.
