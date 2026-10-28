#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hk_plan.py — 把探测结果变成可执行的修复计划

用法:
    python scripts/hk_plan.py --probe probe.json --out plan.json
    python scripts/hk_plan.py --probe probe.json --snapshot snap.json
    python scripts/hk_plan.py --record "Alt+A=微信" --snapshot snap.json   # 记住上次裁决

退出码: 0 无冲突 / 1 存在需处理的冲突 / 2 输入错误

判定规则（写死，可复核）:
    被占用 + 候选 >= 2      -> 需裁决，默认保留上次记录或置信度最高的软件
    被占用 + 候选 == 1      -> 疑似该软件，先退出它复测确认，再进它的设置关掉
    被占用 + 无候选         -> 归属未知，走人工识别，不猜
    系统保留键              -> 标灰，不提供任何修改动作
    纯修饰键（Ctrl+Shift）  -> 探测不到，只给设置核查指引
同输入必得同输出：输出不含时间戳，除 --record 外不改任何文件。
"""

import argparse
import json
import os
import sys

SCHEMA = "hotkey-plan/1"
CONF_RANK = {"high": 3, "medium": 2, "low": 1}


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def claimants_for(catalog, combo):
    for c in catalog.get("combos", []):
        if c.get("combo") == combo:
            return c.get("claimants", []), c
    return [], {}


def pick_default(claimants, remembered):
    """默认保留者：先看上次裁决，再看置信度，最后看字母序。确定性。"""
    if remembered:
        return remembered, "snapshot"
    confident = [c for c in claimants if c.get("confidence") in ("high", "medium")] or claimants
    if not confident:
        return "", "none"
    best = sorted(confident, key=lambda c: (-CONF_RANK.get(c.get("confidence"), 0), c.get("app", "")))
    return best[0]["app"], "confidence"


def build(probe, catalog, snapshot):
    conflicts, clean, blocked, unseen, errors = [], [], [], [], []
    for row in probe.get("combos", []):
        combo, status = row.get("combo", ""), row.get("status", "")
        if status == "reserved":
            blocked.append({"combo": combo, "why": row.get("why", "系统保留，任何第三方都改不了")})
            continue
        if status == "unprobable":
            unseen.append({"combo": combo, "why": row.get("why", "探测不到，只能人工核查")})
            continue
        if status == "error":
            errors.append({"combo": combo, "winerror": row.get("winerror")})
            continue
        if status != "taken":
            clean.append(combo)
            continue

        claimants, entry = claimants_for(catalog, combo)
        strong = [c for c in claimants if c.get("confidence") in ("high", "medium")]
        default_keeper, source = pick_default(claimants, snapshot.get(combo))
        item = {
            "combo": combo,
            "tier": row.get("tier") or entry.get("tier", ""),
            "tier_name": row.get("tier_name") or entry.get("tier_name", ""),
            "symptom": entry.get("symptom", "按了没反应，或出来的不是你要的那个程序"),
            "suspected": [{"app": c.get("app"), "confidence": c.get("confidence"),
                           "fix": c.get("fix", "")} for c in claimants],
            "default_keeper": default_keeper,
            "default_source": source,
        }
        if len(strong) >= 2:
            item["kind"] = "multi"
            item["decide_required"] = True
            item["actions"] = [
                {"type": "decide_keeper", "auto": "manual",
                 "say": "这组键被多个软件同时看上，只能留一个：%s" % "、".join(c["app"] for c in strong)},
                {"type": "verify_by_exit", "auto": "manual",
                 "say": "留谁由你定；定完逐个退出没被留下的软件，复测一次确认已释放"},
            ]
        elif len(strong) == 1:
            app = strong[0]["app"]
            item["kind"] = "single"
            item["decide_required"] = False
            item["actions"] = [
                {"type": "verify_by_exit", "auto": "manual",
                 "say": "先完全退出 %s，再复测 %s；变空闲就说明占用者确实是它" % (app, combo)},
                {"type": "disable_in_app", "auto": "guide",
                 "say": "确认后进 %s 关掉这组键：%s" % (app, strong[0].get("fix", "在它的设置里找到快捷键页"))},
            ]
        else:
            item["kind"] = "unknown"
            item["decide_required"] = True
            item["actions"] = [
                {"type": "identify", "auto": "manual",
                 "say": "候选库里没有对得上的软件；按托盘图标逐个退出常驻软件，每退一个复测一次，退到哪个变空闲就是它"},
            ]
        conflicts.append(item)

    drivers = []
    for d in probe.get("drivers", []):
        drivers.append({"name": d.get("name"), "hit": d.get("hit"),
                        "switch": d.get("switch"),
                        "action": {"type": "driver_switch", "auto": "guide",
                                   "say": "鼠标乱打字或侧键连招：打开 %s 的全局宏开关并关掉，一个开关管全部侧键" % d.get("name")}})

    def order(c):
        kind_rank = {"multi": 0, "unknown": 1, "single": 2}.get(c["kind"], 3)
        return (kind_rank, c["combo"])

    conflicts.sort(key=order)
    multi = [c for c in conflicts if c["kind"] == "multi"]
    n_decide = len([c for c in conflicts if c.get("decide_required")])

    if not conflicts:
        headline = "没有发现被占用的快捷键，当前这套键是干净的。"
        highlights = []
    else:
        if n_decide:
            headline = "检测到 %d 处快捷键被占用，其中 %d 处需要你选一个保留。" % (len(conflicts), n_decide)
        else:
            headline = "检测到 %d 处快捷键被占用，都能直接指路，不需要你选。" % len(conflicts)
        highlights = []
        for c in conflicts[:2]:
            if c["kind"] == "multi":
                names = "、".join(s["app"] for s in c["suspected"] if s["confidence"] in ("high", "medium"))
                highlights.append("`%s`：%s 都会绑它" % (c["combo"], names))
            elif c["kind"] == "single":
                highlights.append("`%s`：最可能是 %s" % (c["combo"], c["suspected"][0]["app"]))
            else:
                highlights.append("`%s`：查不到是谁占的" % c["combo"])
        if len(conflicts) > 2:
            highlights.append("另外 %d 处同类问题，都在下面的表里" % (len(conflicts) - 2))

    safe = [c for c in catalog.get("safe_pool", []) if c not in conflicts]
    return {
        "schema": SCHEMA,
        "host": probe.get("host", ""),
        "probed": len(probe.get("combos", [])),
        "headline": headline,
        "highlights": highlights,
        "counts": {"conflicts": len(conflicts), "decide": n_decide,
                   "multi": len(multi), "clean": len(clean),
                   "reserved": len(blocked), "unprobable": len(unseen), "error": len(errors)},
        "conflicts": conflicts,
        "clean": clean,
        "reserved": blocked,
        "unprobable": unseen,
        "errors": errors,
        "drivers": drivers,
        "safe_keys": safe[:3],
        "caveats": probe.get("caveats", []),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成快捷键冲突修复计划")
    ap.add_argument("--probe", default="probe.json")
    ap.add_argument("--catalog", default=os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "assets", "hotkey-catalog.json"))
    ap.add_argument("--snapshot", default="snapshot.json")
    ap.add_argument("--out", default="plan.json")
    ap.add_argument("--record", default="", help="记录裁决，格式 组合=软件，可多次用逗号分隔")
    args = ap.parse_args(argv)

    snapshot = {}
    if os.path.isfile(args.snapshot):
        try:
            snapshot = load_json(args.snapshot)
        except ValueError:
            snapshot = {}

    if args.record:
        changed = {}
        for pair in args.record.split(","):
            if "=" not in pair:
                sys.stderr.write("--record 格式应为 组合=软件: %s\n" % pair.strip())
                return 2
            k, v = pair.split("=", 1)
            changed[k.strip()] = v.strip()
        snapshot.update(changed)
        with open(args.snapshot, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=2, sort_keys=True)
        print("已记住 %d 条裁决 -> %s" % (len(changed), os.path.abspath(args.snapshot)))
        return 0

    if not os.path.isfile(args.probe):
        sys.stderr.write("probe 文件不存在: %s\n" % args.probe)
        return 2
    try:
        probe = load_json(args.probe)
        catalog = load_json(args.catalog)
    except ValueError as exc:
        sys.stderr.write("JSON 解析失败: %s\n" % exc)
        return 2

    plan = build(probe, catalog, snapshot)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=2)
    print(plan["headline"])
    print("plan -> %s  冲突 %d（需裁决 %d）/ 空闲 %d / 系统保留 %d / 探测不到 %d"
          % (os.path.abspath(args.out), plan["counts"]["conflicts"], plan["counts"]["decide"],
             plan["counts"]["clean"], plan["counts"]["reserved"], plan["counts"]["unprobable"]))
    return 1 if plan["counts"]["conflicts"] else 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
