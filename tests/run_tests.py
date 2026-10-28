#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_tests.py — 包内回归用例（正例 / 反例 / 空输入）

用法: python tests/run_tests.py
退出码: 0 全绿 / 1 有红

用例只跑确定性环节：hk_plan 的判定、hk_report 的渲染、hk_probe 的候选清单。
实机探测依赖当前机器状态，不进回归。
改代码后整批重跑，不许只跑失败那条。
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts")
CATALOG = os.path.join(ROOT, "assets", "hotkey-catalog.json")

RESULTS = []


def run(args, cwd):
    proc = subprocess.run([sys.executable] + args, cwd=cwd,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return (proc.returncode,
            proc.stdout.decode("utf-8", "replace"),
            proc.stderr.decode("utf-8", "replace"))


def write(path, obj):
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False))


def probe(rows, drivers=None):
    return {"schema": "hotkey-probe/1", "host": "TEST-PC", "counts": {},
            "combos": rows, "drivers": drivers or [], "unresolved": [], "caveats": []}


def case(name, fn):
    try:
        fn()
        RESULTS.append((name, True, "ok"))
        print(" + %-34s ok" % name)
    except AssertionError as exc:
        RESULTS.append((name, False, str(exc)))
        print(" - %-34s FAIL  %s" % (name, exc))


# ---------------------------------------------------------------- 用例

def t_multi_conflict():
    """两个候选同时指向一组键 -> 需裁决，默认保留置信度最高者。"""
    tmp = tempfile.mkdtemp(prefix="hk-")
    try:
        write(os.path.join(tmp, "probe.json"), probe([
            {"combo": "Alt+A", "status": "taken", "winerror": 1409, "tier": "T1"},
            {"combo": "F3", "status": "free"},
        ]))
        code, out, err = run([os.path.join(SCRIPT, "hk_plan.py"), "--probe", "probe.json",
                              "--catalog", CATALOG, "--out", "plan.json", "--snapshot", "nope.json"], tmp)
        assert code == 1, "冲突时退出码应为 1，实得 %d" % code
        plan = json.load(io.open(os.path.join(tmp, "plan.json"), encoding="utf-8"))
        c = plan["conflicts"][0]
        assert c["kind"] == "multi", "应为 multi，实得 %s" % c["kind"]
        assert c["decide_required"] is True, "multi 必须要求裁决"
        assert c["default_keeper"] == "微信", "默认保留者应为微信，实得 %s" % c["default_keeper"]
        assert c["default_source"] == "confidence", "默认来源应为置信度"
        assert len(c["suspected"]) == 2, "候选应为 2 个"
        assert plan["highlights"], "首屏应给 1 到 2 条要点"
        assert len(plan["highlights"]) <= 3, "首屏要点不宜超过 3 条"
        assert "Alt+A" in plan["highlights"][0], "要点第一条应指向最要紧的组合"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_single_suspected():
    """单一候选 -> 不出裁决表，出「退出软件后复测」的验证动作。"""
    tmp = tempfile.mkdtemp(prefix="hk-")
    try:
        write(os.path.join(tmp, "probe.json"), probe([
            {"combo": "F3", "status": "taken", "winerror": 1409, "tier": "T1"},
        ]))
        run([os.path.join(SCRIPT, "hk_plan.py"), "--probe", "probe.json", "--catalog", CATALOG,
             "--out", "plan.json", "--snapshot", "nope.json"], tmp)
        plan = json.load(io.open(os.path.join(tmp, "plan.json"), encoding="utf-8"))
        c = plan["conflicts"][0]
        assert c["kind"] == "single", "应为 single，实得 %s" % c["kind"]
        assert c["decide_required"] is False, "单一候选不该要求裁决"
        kinds = [a["type"] for a in c["actions"]]
        assert "verify_by_exit" in kinds, "缺少退出软件后复测的动作: %s" % kinds
        assert "disable_in_app" in kinds, "缺少进软件设置关闭的动作: %s" % kinds
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_unknown_owner():
    """候选库里没有的键 -> 归属未知，不猜名字。"""
    tmp = tempfile.mkdtemp(prefix="hk-")
    try:
        write(os.path.join(tmp, "probe.json"), probe([
            {"combo": "Ctrl+Alt+F7", "status": "taken", "winerror": 1409},
        ]))
        run([os.path.join(SCRIPT, "hk_plan.py"), "--probe", "probe.json", "--catalog", CATALOG,
             "--out", "plan.json", "--snapshot", "nope.json"], tmp)
        plan = json.load(io.open(os.path.join(tmp, "plan.json"), encoding="utf-8"))
        c = plan["conflicts"][0]
        assert c["kind"] == "unknown", "应为 unknown，实得 %s" % c["kind"]
        assert c["suspected"] == [], "未知归属不该编造候选"
        assert c["actions"][0]["type"] == "identify", "应给出识别办法"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_empty_probe():
    """空探测结果 -> 无冲突、退出码 0，不报错。"""
    tmp = tempfile.mkdtemp(prefix="hk-")
    try:
        write(os.path.join(tmp, "probe.json"), probe([]))
        code, out, _ = run([os.path.join(SCRIPT, "hk_plan.py"), "--probe", "probe.json",
                            "--catalog", CATALOG, "--out", "plan.json", "--snapshot", "nope.json"], tmp)
        assert code == 0, "空输入应返回 0，实得 %d" % code
        plan = json.load(io.open(os.path.join(tmp, "plan.json"), encoding="utf-8"))
        assert plan["counts"]["conflicts"] == 0, "空输入不该有冲突"
        assert "没有发现" in plan["headline"], "空输入应给「没有发现」的结论"
        assert plan["highlights"] == [], "空输入不该有要点行"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_reserved_greyed():
    """系统保留键 -> 进 reserved，不给任何修改动作。"""
    tmp = tempfile.mkdtemp(prefix="hk-")
    try:
        write(os.path.join(tmp, "probe.json"), probe([
            {"combo": "Win+L", "status": "reserved", "why": "锁屏，内核级保留"},
            {"combo": "Ctrl+Shift", "status": "unprobable", "why": "裸修饰键"},
        ]))
        run([os.path.join(SCRIPT, "hk_plan.py"), "--probe", "probe.json", "--catalog", CATALOG,
             "--out", "plan.json", "--snapshot", "nope.json"], tmp)
        plan = json.load(io.open(os.path.join(tmp, "plan.json"), encoding="utf-8"))
        assert plan["counts"]["conflicts"] == 0, "保留键不该算冲突"
        assert plan["reserved"][0]["combo"] == "Win+L"
        assert plan["unprobable"][0]["combo"] == "Ctrl+Shift"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_report_idempotent():
    """同一份 plan 渲染两次 -> 字节完全一致。"""
    tmp = tempfile.mkdtemp(prefix="hk-")
    try:
        write(os.path.join(tmp, "plan.json"), {
            "schema": "hotkey-plan/1", "host": "TEST-PC", "probed": 2,
            "headline": "检测到 1 处快捷键被占用：`Alt+A` 被多个软件同时看上（微信、企业微信）。",
            "counts": {"conflicts": 1, "decide": 1, "multi": 1, "clean": 1, "reserved": 0,
                       "unprobable": 0, "error": 0},
            "conflicts": [{"combo": "Alt+A", "kind": "multi", "decide_required": True,
                           "default_keeper": "微信", "default_source": "confidence",
                           "suspected": [{"app": "微信", "confidence": "high", "fix": "微信 设置 快捷键"},
                                         {"app": "企业微信", "confidence": "medium", "fix": "企业微信 设置"}],
                           "actions": [{"type": "decide_keeper", "say": "只能留一个"}]}],
            "clean": ["F3"], "reserved": [], "unprobable": [], "drivers": [], "safe_keys": [],
        })
        run([os.path.join(SCRIPT, "hk_report.py"), "--plan", "plan.json", "--out", "a.html"], tmp)
        run([os.path.join(SCRIPT, "hk_report.py"), "--plan", "plan.json", "--out", "b.html"], tmp)
        a = io.open(os.path.join(tmp, "a.html"), "rb").read()
        b = io.open(os.path.join(tmp, "b.html"), "rb").read()
        assert a == b, "两次渲染结果不一致（%d / %d 字节）" % (len(a), len(b))
        assert b"<script>alert" not in a, "渲染出现未转义脚本"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_report_escapes():
    """组合名与软件名里的标签必须转义，不能原样落进页面。"""
    tmp = tempfile.mkdtemp(prefix="hk-")
    try:
        write(os.path.join(tmp, "plan.json"), {
            "schema": "hotkey-plan/1", "host": "TEST-PC", "probed": 1,
            "headline": "x", "counts": {"conflicts": 1, "decide": 1, "multi": 1, "clean": 0,
                                        "reserved": 0, "unprobable": 0, "error": 0},
            "conflicts": [{"combo": "<b>A</b>", "kind": "multi", "decide_required": True,
                           "default_keeper": "x", "default_source": "confidence",
                           "suspected": [{"app": "<img src=x onerror=1>", "confidence": "low", "fix": ""}],
                           "actions": []}],
            "clean": [], "reserved": [], "unprobable": [], "drivers": [], "safe_keys": [],
        })
        run([os.path.join(SCRIPT, "hk_report.py"), "--plan", "plan.json", "--out", "r.html"], tmp)
        page = io.open(os.path.join(tmp, "r.html"), encoding="utf-8").read()
        assert "<img src=x" not in page, "软件名未转义"
        assert "&lt;img" in page, "应输出转义后的实体"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_bad_json_rejected():
    """坏 JSON -> 退出码 2，不给结果。"""
    tmp = tempfile.mkdtemp(prefix="hk-")
    try:
        io.open(os.path.join(tmp, "bad.json"), "w", encoding="utf-8").write("{not json")
        code, _, _ = run([os.path.join(SCRIPT, "hk_plan.py"), "--probe", "bad.json",
                          "--catalog", CATALOG, "--out", "plan.json"], tmp)
        assert code == 2, "坏 JSON 应返回 2，实得 %d" % code
        code2, _, _ = run([os.path.join(SCRIPT, "hk_report.py"), "--plan", "nope.json",
                           "--out", "r.html"], tmp)
        assert code2 == 2, "缺文件应返回 2，实得 %d" % code2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_snapshot_memory():
    """记住上次裁决 -> 下次默认勾选它，而不是重新按置信度算。"""
    tmp = tempfile.mkdtemp(prefix="hk-")
    try:
        write(os.path.join(tmp, "probe.json"), probe([
            {"combo": "Alt+A", "status": "taken", "winerror": 1409, "tier": "T1"},
        ]))
        code, _, _ = run([os.path.join(SCRIPT, "hk_plan.py"), "--record", "Alt+A=企业微信",
                          "--snapshot", "snap.json"], tmp)
        assert code == 0, "记录裁决应返回 0"
        run([os.path.join(SCRIPT, "hk_plan.py"), "--probe", "probe.json", "--catalog", CATALOG,
             "--out", "plan.json", "--snapshot", "snap.json"], tmp)
        plan = json.load(io.open(os.path.join(tmp, "plan.json"), encoding="utf-8"))
        c = plan["conflicts"][0]
        assert c["default_keeper"] == "企业微信", "应沿用上次裁决，实得 %s" % c["default_keeper"]
        assert c["default_source"] == "snapshot", "来源应标为 snapshot"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_probe_list():
    """--list 只读 catalog，不探测，输出稳定。"""
    code, out, _ = run([os.path.join(SCRIPT, "hk_probe.py"), "--list", "--catalog", CATALOG],
                       tempfile.gettempdir())
    assert code == 0, "--list 应返回 0"
    data = json.loads(out)
    assert len(data["probe"]) >= 12, "候选组合偏少: %d" % len(data["probe"])
    assert "Win+L" in data["reserved"], "系统保留键缺失"
    assert "Ctrl+Shift" in data["unprobable"], "裸修饰键缺失"
    code2, out2, _ = run([os.path.join(SCRIPT, "hk_probe.py"), "--list", "--catalog", CATALOG],
                         tempfile.gettempdir())
    assert out == out2, "--list 两次输出应一致"


def main():
    print("=" * 60)
    print("HOTKEY CONFLICT REPAIR · 包内回归")
    print("-" * 60)
    for name, fn in [("多候选冲突需裁决", t_multi_conflict),
                     ("单候选给验证动作", t_single_suspected),
                     ("未知归属不编造", t_unknown_owner),
                     ("空输入返回干净结论", t_empty_probe),
                     ("系统保留键仅标记", t_reserved_greyed),
                     ("报告渲染幂等", t_report_idempotent),
                     ("报告转义注入字符", t_report_escapes),
                     ("坏输入被拒绝", t_bad_json_rejected),
                     ("沿用上次裁决", t_snapshot_memory),
                     ("候选清单稳定", t_probe_list)]:
        case(name, fn)
    bad = [r for r in RESULTS if not r[1]]
    print("-" * 60)
    print("RESULT %s  %d/%d 通过" % ("PASS" if not bad else "FAIL",
                                     len(RESULTS) - len(bad), len(RESULTS)))
    print("=" * 60)
    return 1 if bad else 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
