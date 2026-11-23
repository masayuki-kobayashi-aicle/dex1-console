# Wiring

ESP-Prog (FT2232H, 0403:6010) + MAX3485 board + the hand's RS485 A/B pair and a common ground.

| ESP-Prog | to | Role |
|---|---|---|
| JTAG pin 8 (TDI, ADBUS1) | MAX3485 board **RXD** terminal | transmit data, bit-banged by channel A |
| JTAG pin 2 (TMS, ADBUS3) | MAX3485 board **EN** | driver enable, clocked out together with the data |
| Program pin 3 (ESP_TXD, channel B) | MAX3485 board **TXD** terminal | receive: the hand's reply |

The board's silkscreen is module-side: the **RXD terminal is the input** and the **TXD terminal is the output**.
Do not wire it the other way round.

## Why this way

The hand answers about 7 us after the query ends, and switching EN over USB (DTR/RTS) takes about 1 ms. So channel A
writes data and EN as one sample stream that the chip clocks out itself (1 sample = 1 bit at 6 MHz), and channel B is
a plain UART used for receiving only.

## DTR and RTS must stay Low

With DTR asserted on channel B the replies stop after about 1 s (measured; the cause is not confirmed). The package
opens channel B with DTR=RTS=Low and discards the first exchange after opening, which is always lost.

## macOS

Measured 2026-11-19 on an Apple-silicon Mac (macOS, Darwin 25.6.0), Python 3.14, libusb from Homebrew, right hand id 7,
6 Mbaud, ESP-Prog moved over from the Linux host:

- No driver change and no sudo were needed: Apple's FTDI driver did not block pyftdi on channel A.
- Both channels appeared as `/dev/cu.usbserial-100` and `-101`; `port_b = "auto"` picked `-101`.
- `dex1 probe` answered, and `dex1 preflight` passed all five stages, including a 0.5 rad test motion
  (10/10 replies, median first-byte delay 15.5 ms; this is host-side latency, not the hand's response time).
- `dex1 console` then opened and closed the hand over the full stroke (0.122 -> 5.083 -> 0.120 rad, no abort, 24.0 V, 30/27 C).

Not verified on macOS: repeated cycles and long runs, other Mac models or macOS versions, and USB hubs.
The interactive commands need a real terminal window (not a pipe or an IDE's `!` command).
