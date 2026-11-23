"""Messages shown to a person, in English and Japanese. Logs (JSONL) and exception text from the config loader stay English.

Language: set_language("en" | "ja" | "auto"). "auto" reads DEX1_LANG, then LC_ALL / LC_MESSAGES / LANG; anything that does
not start with "ja" is English. A key missing in Japanese falls back to English.
"""
from __future__ import annotations

import os

LANGUAGES = ("en", "ja")
_lang = "en"

CATALOG = {  # key: (English, Japanese). Placeholders use str.format.
    # motion / link
    "reply_wrong_id": ("reply from motor {got}, expected {want}", "モーター {got} から返信が来た（期待は {want}）"),
    "merror": ("MError {code:#x}", "モーターが異常を報告（MError {code:#x}）"),
    "over_temp": ("temperature {case}/{coil} C above {limit} C", "温度 {case}/{coil} ℃ が上限 {limit} ℃ を超えた"),
    "track_err": ("position {q:.3f} rad is {err:.3f} rad from the command {target:.3f}",
                  "位置 {q:.3f} rad が指令 {target:.3f} rad から {err:.3f} rad ずれた"),
    "link_error": ("no reply from motor {id} after {n} tries", "モーター {id} から {n} 回続けて返信なし"),
    "target_out": ("target {t:.3f} rad outside {lo}..{hi}", "目標 {t:.3f} rad は範囲 {lo}〜{hi} の外"),
    "uncalibrated": ("the hand reads {q:.3f} rad, outside the expected range; calibrate it first",
                     "ハンドの位置が {q:.3f} rad で、想定の範囲の外。先に校正してください"),
    "move_plan": ("{q0:.3f} -> {target:.3f} rad in {ramp:.1f} s", "{q0:.3f} → {target:.3f} rad を {ramp:.1f} 秒で動かす"),
    "misses": ("{n} missed replies in a row", "返信が {n} 回続けて来なかった"),
    "interrupted": ("interrupted", "中断（Ctrl-C）"),
    "no_reply_after": ("no reply after the move", "動いた後に返信なし"),
    # transport
    "env_detail": ("channel B {ports}; other hand programs: {holders}", "チャンネル B: {ports}、ほかのハンド用プログラム: {holders}"),
    "env_missing": ("missing", "見つからない"),
    "env_none": ("none", "なし"),
    "env_fix": ("plug in the ESP-Prog (0403:6010) and stop other programs that use the hand",
                "ESP-Prog（0403:6010）をつなぎ、ハンドを使うほかのプログラムを止める"),
    # preflight
    "pf_title": ("Preflight", "プリフライト（動かす前の確認）"),
    "pf_pass": ("PASS", "合格"),
    "pf_fail": ("FAIL", "不合格"),
    "pf_fix": ("fix: ", "対処: "),
    "st_env": ("1 environment", "1 環境"),
    "st_link": ("2 link", "2 接続"),
    "st_state": ("3 state", "3 状態"),
    "st_cal": ("4 calibration", "4 校正"),
    "st_motion": ("5 motion", "5 動作"),
    "link_detail": ("{n}/{total} replies, median first-byte delay {ms:.1f} ms",
                    "返信 {n}/{total} 回、最初のバイトまでの遅れの中央値 {ms:.1f} ms"),
    "link_fix": ("check the 24 V supply, the hand's signal cable and the MAX3485 wiring "
                 "(TDI->RXD terminal, TXD terminal->ESP_TXD, TMS->EN); DTR must not be asserted",
                 "24 V 電源、ハンドの信号ケーブル、MAX3485 の配線（TDI→RXD 端子、TXD 端子→ESP_TXD、TMS→EN）を確認。DTR は立てない"),
    "state_detail": ("id {id}, MError {m:#x}, temperature {c}/{k} C, {v:.1f} V",
                     "id {id}、MError {m:#x}、温度 {c}/{k} ℃、{v:.1f} V"),
    "state_fix": ("MError 0x8: unplug the AC adapter, wait 5 s. High temperature: let it cool. Check the supply voltage.",
                  "MError 0x8 は AC アダプタを抜いて 5 秒待つ。温度が高いときは冷ます。電源電圧も確認する"),
    "cal_ask": ("  Visual check: the hand closed itself. Are the fingers fully closed? [Enter = yes, n = no] ",
                "  目視確認: ハンドが自分で閉じた。指は閉じ切っていますか？ [Enter = はい、n = いいえ] "),
    "cal_not_closed": ("the operator saw the fingers not fully closed; the zero was not kept",
                       "操作者が「閉じ切っていない」と見た。ゼロは採用しない"),
    "cal_auto": (" (closed by itself, travelled {travel:.3f} rad)", "（自動で閉じた、移動量 {travel:.3f} rad）"),
    "cal_detail": ("closed reads {q:.3f} rad (expected {exp} +/- {tol})", "閉じた状態の読みは {q:.3f} rad（期待は {exp} ± {tol}）"),
    "cal_fix": ("remove whatever blocks the fingers and run the preflight again; if it stays off, check the zero point",
                "指を塞ぐ物を取り除き、プリフライトをやり直す。それでもずれるなら、ゼロ点を確認する"),
    "motion_detail": ("peak {p:.3f} rad, back to {b:.3f} rad", "最大 {p:.3f} rad、戻りは {b:.3f} rad"),
    "motion_stopped": (", stopped: {r}", "、停止: {r}"),
    "motion_fix": ("see the reason above and the log", "上の理由とログを見る"),
    # console
    "help": ("""\
  (Enter)   move to the other side (closed <-> open)
  o / c     fully open / closed
  g <rad>   go to an absolute angle, e.g. g 2.5
  s         status (angle, temperature, voltage); nothing moves
  t <sec>   time for one move, e.g. t 8 (too short a time is lengthened automatically)
  l on|off  start / stop the JSONL log
  p         run the preflight again
  z         auto zero: close until the finger stops and call that 0 (until you quit)
  b         brake
  h         this help
  q         quit (brakes first)
  Ctrl-C    stop a move in progress and brake""", """\
  (Enter)   今いる側の反対へ動く（閉 ⇄ 開）
  o / c     全開 / 全閉へ
  g <rad>   絶対位置へ動く（例: g 2.5）
  s         状態（位置・温度・電圧）。動かさない
  t <秒>    1 回の動きの時間（例: t 8。短すぎる値は自動で延ばす）
  l on|off  ログ（JSONL）の開始・停止
  p         プリフライトをもう一度行う
  z         自動ゼロ: 指が止まるまで閉じ、その位置を 0 にする（終了まで有効）
  b         BRAKE（保持）
  h         このヘルプ
  q         終了（先に BRAKE する）
  Ctrl-C    動いている途中で止めて BRAKE"""),
    "help_hint": ("h for help", "h でヘルプ"),
    "log_path": ("log: {path}", "ログ: {path}"),
    "log_closed": ("log closed: {path}", "ログを閉じた: {path}"),
    "refused": ("refused: {e}", "実行しない: {e}"),
    "now": ("now {q:.3f} rad", "現在 {q:.3f} rad"),
    "stopped": ("  STOPPED: {reason} (braked)", "  停止: {reason}（BRAKE 済み）"),
    "no_answer": ("no answer: {e}", "返信なし: {e}"),
    "status": ("q {q:.3f} rad  temp {c}/{k} C  {v:.1f} V  MError {m:#x}  ramp {r:.1f} s  log {log}",
               "位置 {q:.3f} rad  温度 {c}/{k} ℃  {v:.1f} V  MError {m:#x}  動作時間 {r:.1f} 秒  ログ {log}"),
    "on": ("on", "オン"),
    "off": ("off", "オフ"),
    "ramp_set": ("ramp {s:.1f} s", "動作時間 {s:.1f} 秒"),
    "usage_log": ("usage: l on | l off", "使い方: l on | l off"),
    "pf_ok": ("preflight OK", "プリフライト OK"),
    "pf_ng": ("preflight FAILED: fix it before moving", "プリフライト NG: 直してから動かす"),
    "unknown_cmd": ("unknown command {cmd!r}; h for help", "{cmd!r} というコマンドは無い。h でヘルプ"),
    "not_number": ("{arg!r} is not a number", "{arg!r} は数値ではない"),
    "bad_value": ("bad value", "値が正しくない"),
    # cli
    "selftest_ok": ("selftest: frames match the vendor SDK output", "selftest: フレームが公式 SDK の出力と一致した"),
    "selftest_bad": ("selftest: MISMATCH", "selftest: 不一致"),
    "no_reply": ("id={id} NO-REPLY", "id={id} 返信なし（NO-REPLY）"),
    "no_terminal": ("this command asks questions and needs an interactive terminal (stdin is not a terminal). "
                    "Run it in a terminal window, not through a pipe, a script or an IDE's '!' command.",
                    "このコマンドは質問をするので、対話できるターミナルが必要です（標準入力が端末ではない）。"
                    "パイプ、スクリプト、IDE の「!」コマンドではなく、ターミナルのウィンドウで実行してください。"),
    "input_closed": ("\ninput closed during the preflight; nothing was moved", "\nプリフライト中に入力が閉じた。ハンドは動かしていない"),
    "pf_start_failed": ("preflight FAILED; fix it and start again (--skip-preflight to bypass)",
                        "プリフライト NG。直してからもう一度起動する（--skip-preflight で省略できる）"),
    "wrote": ("wrote {out} ({n} rows)", "{out} に書き出した（{n} 行）"),
    "error": ("error: {e}", "エラー: {e}"),
    # gui
    "gui_url": ("GUI: {url}  (Ctrl-C to stop; this server accepts connections from this computer only)",
                "GUI: {url}  （Ctrl-C で終了。このサーバーはこのコンピューターからの接続だけを受け付ける）"),
    "gui_busy": ("busy with {name}; press Stop to interrupt", "{name} の実行中。中断するには「停止」を押す"),
    "gui_not_connected": ("not connected: press Connect first", "未接続。先に「接続」を押す"),
    "gui_need_preflight": ("run the preflight first (it must pass before the hand moves)",
                           "先にプリフライトを行う（合格するまでハンドは動かさない）"),
    "gui_unknown_action": ("unknown action {name!r}", "{name!r} という操作は無い"),
    "gui_bad_id": ("motor id must be a whole number 0..15, got {value}", "モーター ID は 0〜15 の整数（受け取った値: {value}）"),
    "gui_id_note": ("id {id}: the default limits were measured on id 7 only; check the first moves closely",
                    "id {id}: 標準の安全限界は id 7 でしか測っていない。最初の動きはよく見る"),
    "zero_plan": ("auto zero: closing from {q0:.3f} rad at {speed:g} rad/s until the finger stops (Stop brakes at once)",
                  "自動ゼロ: {q0:.3f} rad から {speed:g} rad/s で閉じ、指が止まるまで続ける（停止ボタンですぐ BRAKE）"),
    "zero_no_stop": ("no stop found within the full stroke", "全行程を閉じても止まらなかった"),
    "zero_implausible": ("stopped at {q:.3f} rad, but a closed hand reads about {exp:g} rad (tolerance {tol:g}); something may be blocking the finger. The zero was not changed",
                         "{q:.3f} rad で止まったが、閉じ切ったハンドは約 {exp:g} rad（許容 {tol:g}）。指を何かが塞いでいるかもしれない。ゼロは変えていない"),
    "zero_done": ("auto zero done: the closed stop is now 0 rad (it was {zero:.3f} rad in the hand's own angle; travelled {travel:.3f} rad). Kept until you disconnect",
                  "自動ゼロ完了: 閉じ側の止まった位置を 0 rad にした（ハンド自身の角度では {zero:.3f} rad、移動量 {travel:.3f} rad）。切断するまで有効"),
    "zero_failed": ("auto zero stopped: {reason}", "自動ゼロを中止: {reason}"),
    "zero_look": (" Check by eye that the hand is fully closed. ", " 指が閉じ切っているか目視で確認する。 "),
    "zero_rerun_pf": ("run the preflight again before moving", "動かす前にプリフライトをやり直す"),
    "bad_strength": ("strength must be a number", "強さは数値で指定する"),
    "ramp_and_speed": ("give a time or a speed, not both", "時間と速度は同時に指定できない。どちらか一方にする"),
    "gui_bad_lang": ("language must be \"en\" or \"ja\", got {value}", "言語は \"en\" か \"ja\" のどちらか（受け取った値: {value}）"),
    "gui_connected": ("connected: id {id}", "接続した: id {id}"),
    "gui_disconnected": ("disconnected (braked)", "切断した（BRAKE 済み）"),
    "gui_already": ("already connected", "すでに接続している"),
    "gui_braked": ("braked", "BRAKE した"),
    "gui_stopping": ("stop requested", "停止を要求した"),
    "gui_dialog_closed": ("question dialog closed without an answer; nothing was moved",
                          "質問に答えないまま終わった。ハンドは動かしていない"),
}


def resolve(lang: str) -> str:
    if lang in LANGUAGES:
        return lang
    if lang != "auto":
        raise ValueError(f"unknown language {lang!r} (en, ja or auto)")
    for var in ("DEX1_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "")
        if value:
            return "ja" if value.lower().startswith("ja") else "en"
    return "en"


def set_language(lang: str) -> str:
    global _lang
    _lang = resolve(lang)
    return _lang


def language() -> str:
    return _lang


def t(key: str, **kw: object) -> str:
    en, ja = CATALOG[key]
    return (ja if _lang == "ja" and ja else en).format(**kw)
