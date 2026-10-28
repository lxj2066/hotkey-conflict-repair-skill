#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hk_probe.py — Windows 全局热键占用实机探测

用法:
    python scripts/hk_probe.py                     # 按 catalog 全量探测，输出 probe.json
    python scripts/hk_probe.py --out probe.json    # 指定输出文件
    python scripts/hk_probe.py --combos "Alt+A,Win+Shift+S"
    python scripts/hk_probe.py --list              # 只列候选组合，不探测（确定性，可回归）
    python scripts/hk_probe.py --no-process        # 跳过进程枚举（无权限环境）

退出码: 0 探测完成（有冲突也算完成） / 2 环境或参数错误

原理: 用 RegisterHotKey 试探每个组合，紧接着立即注销。返回 1409
(ERROR_HOTKEY_ALREADY_REGISTERED) 说明该组合已被本会话里的某个程序注册。
探测只登记再注销，不触发任何程序，不改任何配置。
局限: 只覆盖走 RegisterHotKey 的程序；走低级键盘钩子、驱动或轮询键状态的程序
探测不到（这类按键会显示为空闲，需用「退出软件后复测」或人工核查兜底）。
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import datetime

SCHEMA = "hotkey-probe/1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CATALOG = os.path.join(os.path.dirname(HERE), "assets", "hotkey-catalog.json")

MODS = {"CTRL": 0x0002, "CONTROL": 0x0002, "ALT": 0x0001,
        "SHIFT": 0x0004, "WIN": 0x0008, "META": 0x0008}
MOD_NOREPEAT = 0x4000
ERR_ALREADY = 1409

VK_EXTRA = {
    "PRINTSCREEN": 0x2C, "SNAPSHOT": 0x2C, "SPACE": 0x20, "TAB": 0x09,
    "ESC": 0x1B, "ESCAPE": 0x1B, "INSERT": 0x2D, "DELETE": 0x2E,
    "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "PAUSE": 0x13, "GRAVE": 0xC0, "BACKSPACE": 0x08, "ENTER": 0x0D,
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    "PERIOD": 0xBE, ".": 0xBE, "COMMA": 0xBC, ",": 0xBC,
    "SLASH": 0xBF, "SEMICOLON": 0xBA, "MINUS": 0xBD, "BACKTICK": 0xC0,
    "PRTSC": 0x2C,
}


def parse_combo(text):
    """'Ctrl+Alt+A' -> (mods_bitmask, vk)。解析不出返回 (None, None)。"""
    parts = [p.strip().upper() for p in str(text).replace("＋", "+").split("+") if p.strip()]
    if not parts:
        return None, None
    mods, key = 0, None
    for p in parts:
        if p in MODS:
            mods |= MODS[p]
            continue
        if key is not None:
            return None, None
        if len(p) == 1 and (p.isdigit() or "A" <= p <= "Z"):
            key = ord(p)
        elif p.startswith("F") and p[1:].isdigit() and 1 <= int(p[1:]) <= 24:
            key = 0x70 + int(p[1:]) - 1
        elif p in VK_EXTRA:
            key = VK_EXTRA[p]
        else:
            return None, None
    if key is None:
        return None, None
    return mods, key


def probe_one(mods, vk, slot=0x8F01):
    """返回 (status, winerror)。status: taken / free / error"""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    try:
        ctypes.set_last_error(0)
        ok = user32.RegisterHotKey(None, slot, mods | MOD_NOREPEAT, vk)
        err = ctypes.get_last_error()
        if ok:
            user32.UnregisterHotKey(None, slot)
            return "free", 0
        if err == ERR_ALREADY:
            return "taken", err
        return "error", err
    except Exception:
        return "error", -1


def running_processes():
    """枚举当前进程名（小写）。失败返回空集合。"""
    names = set()
    try:
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        arr = (wt.DWORD * 4096)()
        need = wt.DWORD(0)
        if not psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(need)):
            return names
        count = need.value // ctypes.sizeof(wt.DWORD)
        for i in range(count):
            pid = arr[i]
            if not pid:
                continue
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                continue
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wt.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    names.add(os.path.basename(buf.value).lower())
            finally:
                kernel32.CloseHandle(handle)
    except Exception:
        return names
    return names


def load_catalog(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Windows 全局热键占用探测")
    ap.add_argument("--catalog", default=DEFAULT_CATALOG)
    ap.add_argument("--combos", default="", help="额外探测的组合，逗号分隔")
    ap.add_argument("--out", default="probe.json")
    ap.add_argument("--list", action="store_true", help="只列候选组合，不探测")
    ap.add_argument("--no-process", action="store_true")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.catalog):
        sys.stderr.write("catalog 不存在: %s\n" % args.catalog)
        return 2
    try:
        cat = load_catalog(args.catalog)
    except ValueError as exc:
        sys.stderr.write("catalog 不是合法 JSON: %s\n" % exc)
        return 2

    reserved = {r["combo"]: r for r in cat.get("reserved", [])}
    unprobable = {u["combo"]: u for u in cat.get("unprobable", [])}
    known = {c["combo"]: c for c in cat.get("combos", [])}

    extra = [c.strip() for c in args.combos.split(",") if c.strip()]

    if args.list:
        out = {"schema": SCHEMA, "catalog_version": cat.get("version"),
               "probe": sorted(known), "reserved": sorted(reserved),
               "unprobable": sorted(unprobable), "extra": sorted(extra)}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if os.name != "nt":
        sys.stderr.write("本脚本只支持 Windows\n")
        return 2

    rows, unresolved = [], []
    for combo in sorted(set(known) | set(extra) | set(reserved) | set(unprobable)):
        mods, vk = parse_combo(combo)
        entry = known.get(combo, {})
        if combo in reserved:
            rows.append({"combo": combo, "status": "reserved", "tier": reserved[combo].get("tier"),
                         "why": reserved[combo].get("why")})
            continue
        if combo in unprobable:
            rows.append({"combo": combo, "status": "unprobable", "tier": unprobable[combo].get("tier"),
                         "why": unprobable[combo].get("why")})
            continue
        if mods is None:
            unresolved.append(combo)
            continue
        status, err = probe_one(mods, vk)
        rows.append({"combo": combo, "status": status, "winerror": err,
                     "tier": entry.get("tier"), "tier_name": entry.get("tier_name")})

    procs = set() if args.no_process else running_processes()
    drivers = []
    for d in cat.get("drivers", []):
        hit = [p for p in d.get("processes", []) if p.lower() in procs]
        if hit:
            drivers.append({"name": d["name"], "hit": hit[0], "switch": d.get("switch")})

    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    payload = {
        "schema": SCHEMA,
        "catalog_version": cat.get("version"),
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "host": os.environ.get("COMPUTERNAME", ""),
        "counts": counts,
        "combos": rows,
        "drivers": drivers,
        "unresolved": sorted(unresolved),
        "caveats": [
            "只覆盖走 RegisterHotKey 的程序；钩子类与驱动类占用探测不到",
            "探测到占用只能说明「被占了」，不能直接给出占用者",
        ],
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print("probe -> %s  已探测 %d 项  taken %d / free %d / reserved %d / unprobable %d / error %d"
          % (os.path.abspath(args.out), len(rows), counts.get("taken", 0), counts.get("free", 0),
             counts.get("reserved", 0), counts.get("unprobable", 0), counts.get("error", 0)))
    if drivers:
        print("检测到驱动软件: %s" % "、".join(d["name"] for d in drivers))
    if unresolved:
        print("无法解析的组合: %s" % ", ".join(unresolved))
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
