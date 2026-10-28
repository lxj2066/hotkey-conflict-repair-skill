#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hk_report.py — 把修复计划渲染成一张可直接照着做的单页 HTML

用法:
    python scripts/hk_report.py --plan plan.json --out report.html

退出码: 0 生成成功 / 2 输入错误

页面只有三件事：一句话说清问题、一张表让用户选保留谁、一条复测路径。
同输入必得同输出：输出不含时间戳与随机数。
"""

import argparse
import html
import json
import os
import sys

POP = {"high": "高", "medium": "中", "low": "低"}

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font:15px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:#1d2129;
background:#f5f6f8;padding:32px 18px;-webkit-font-smoothing:antialiased}
.wrap{max-width:820px;margin:0 auto;background:#fff;border:1px solid #e3e6eb;
border-radius:14px;padding:34px 34px 28px;box-shadow:0 1px 2px rgba(16,24,40,.04)}
h1{font-size:19px;font-weight:650;letter-spacing:.2px}
.sub{color:#7a828e;font-size:12.5px;margin-top:6px}
.say{margin:22px 0 6px;font-size:16.5px;line-height:1.7}
.say b{color:#c0392b;font-weight:650}
.hl{margin:6px 0 0 20px;font-size:14px;color:#4b5563}
.hl li{margin:3px 0}
h2{font-size:13px;font-weight:650;color:#5b636e;letter-spacing:.6px;
margin:30px 0 10px;padding-bottom:7px;border-bottom:1px solid #eef0f3}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;font-weight:600;color:#7a828e;font-size:12px;letter-spacing:.4px;
padding:8px 10px;border-bottom:1px solid #e8ebef;white-space:nowrap}
td{padding:11px 10px;border-bottom:1px solid #f1f3f6;vertical-align:top}
tr:last-child td{border-bottom:0}
kbd{font:500 13px/1 Consolas,monospace;background:#f3f5f8;border:1px solid #dfe3e9;
border-bottom-width:2px;border-radius:5px;padding:5px 8px;white-space:nowrap;display:inline-block}
label{display:block;padding:3px 0;cursor:pointer}
label input{margin-right:7px;vertical-align:-1px}
.tag{display:inline-block;font-size:11px;padding:1px 6px;border-radius:4px;
background:#eef1f5;color:#6b7280;margin-left:6px;vertical-align:1px}
.st{font-size:12.5px;color:#a33;white-space:nowrap}
.st.ok{color:#2e7d32}.st.gray{color:#98a1ad}
.why{color:#6b7280;font-size:12.5px;margin-top:3px}
.muted{color:#98a1ad}
.gray{opacity:.6}
.note{background:#fafbfc;border:1px solid #eceff3;border-radius:9px;
padding:14px 16px;font-size:13.5px;color:#4b5563;margin-top:12px}
.note ol,.note ul{margin:6px 0 0 18px}.note li{margin:4px 0}
.btn{font:inherit;font-weight:600;background:#1d2129;color:#fff;border:0;border-radius:8px;
padding:11px 20px;cursor:pointer;margin-top:16px}
.btn:hover{background:#000}
pre{background:#f7f8fa;border:1px solid #eceff3;border-radius:8px;padding:13px;
font:13px/1.6 Consolas,monospace;white-space:pre-wrap;margin-top:12px;display:none}
pre.on{display:block}
.foot{margin-top:26px;padding-top:14px;border-top:1px solid #eef0f3;
font-size:12px;color:#98a1ad;line-height:1.75}
"""

JS = """
function build(){
  var out=[], rows=document.querySelectorAll('tr[data-combo]');
  rows.forEach(function(r){
    var c=r.getAttribute('data-combo'), pick=r.querySelector('input:checked');
    if(!pick) return;
    if(pick.value==='__none__') return;
    out.push(c+' 保留 '+pick.value);
  });
  var box=document.getElementById('confirm');
  if(!out.length){ box.textContent='还没选任何一项。不想动的行留空即可。'; }
  else { box.textContent='请按这份清单修复：\\n'+out.map(function(s){return '· '+s}).join('\\n'); }
  box.classList.add('on');
}
"""


def esc(v):
    return html.escape(str(v or ""), quote=True)


def row_conflict(c):
    name = esc(c["combo"])
    opts = []
    for s in c.get("suspected", []):
        checked = " checked" if s["app"] == c.get("default_keeper") else ""
        conf = POP.get(s.get("confidence"), "?")
        opts.append(
            '<label><input type="radio" name="%s" value="%s"%s>%s'
            '<span class="tag">可能性%s</span></label>'
            % (name, esc(s["app"]), checked, esc(s["app"]), conf))
    opts.append('<label><input type="radio" name="%s" value="__none__">都先不动</label>' % name)
    why = ""
    if c.get("kind") == "multi":
        st = '<span class="st">多个软件在抢</span>'
    elif c.get("kind") == "single":
        st = '<span class="st">已被占用</span>'
    else:
        st = '<span class="st">已被占用，来源不明</span>'
        why = '<div class="why">候选库里没有对得上的软件，按下面的识别办法查</div>'
    if c.get("default_source") == "snapshot":
        why = '<div class="why">默认勾选的是你上次的选择</div>'
    return ('<tr data-combo="%s"><td><kbd>%s</kbd></td><td>%s</td><td>%s%s</td></tr>'
            % (name, name, "".join(opts), st, why))


def row_plain(combo, note, label, cls=""):
    return ('<tr><td><kbd>%s</kbd></td><td class="muted">%s</td>'
            '<td><span class="st %s">%s</span></td></tr>'
            % (esc(combo), note, cls, label))


def render(plan):
    conflicts = plan.get("conflicts", [])
    parts = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>快捷键体检报告</title><style>', CSS, '</style></head><body><div class="wrap">',
             '<h1>快捷键体检</h1>',
             '<div class="sub">实机探测结果，只登记再注销，没有改动任何软件设置</div>',
             '<p class="say">%s</p>' % esc(plan.get("headline", "")).replace("`", ""),
             '<ul class="hl">%s</ul>' % "".join(
                 "<li>%s</li>" % esc(h).replace("`", "") for h in (plan.get("highlights") or [])),
             '<p class="sub">设备 %s　探测 %d 项　冲突 %d　空闲 %d　系统保留 %d　探测不到 %d</p>'
             % (esc(plan.get("host", "")), plan.get("probed", 0),
                plan.get("counts", {}).get("conflicts", 0), plan.get("counts", {}).get("clean", 0),
                plan.get("counts", {}).get("reserved", 0), plan.get("counts", {}).get("unprobable", 0))]

    if conflicts:
        parts.append('<h2>要你选一下的键</h2><table><tr><th style="width:24%">快捷键</th>'
                     '<th>保留哪个程序</th><th style="width:22%">当前状态</th></tr>')
        for c in conflicts:
            parts.append(row_conflict(c))
        parts.append('</table>')
        parts.append('<button class="btn" onclick="build()">生成确认清单</button>'
                     '<pre id="confirm"></pre>')

        steps = []
        for c in conflicts:
            for a in c.get("actions", []):
                steps.append("<li><kbd>%s</kbd> %s</li>" % (esc(c["combo"]), esc(a.get("say"))))
        parts.append('<h2>按这个顺序动手</h2><div class="note"><ol>%s</ol>'
                     '<div style="margin-top:9px">改完回到对话里说一声，重新体检一次核对。</div></div>'
                     % "".join(steps))
    else:
        parts.append('<div class="note">没有需要处理的冲突。常用的键都空着，直接用就行。</div>')

    if plan.get("drivers"):
        parts.append('<h2>鼠标侧键与驱动宏</h2><div class="note"><ul>')
        for d in plan["drivers"]:
            parts.append("<li>检测到 <b>%s</b> 正在运行（%s）。%s</li>"
                         % (esc(d["name"]), esc(d["hit"]), esc(d.get("action", {}).get("say", ""))))
        parts.append('</ul><div style="margin-top:9px">驱动宏不走热键表，热键探测查不到它，'
                     '关掉总开关是最快的一条路。</div></div>')

    if plan.get("reserved"):
        parts.append('<h2>系统保留键（不用试，改不了）</h2><table><tr>'
                     '<th style="width:28%">快捷键</th><th>为什么动不了</th><th style="width:18%">状态</th></tr>')
        for r in plan["reserved"]:
            parts.append(row_plain(r["combo"], esc(r.get("why", "")), "系统保留", "gray"))
        parts.append('</table>')

    if plan.get("unprobable"):
        parts.append('<h2>探测不到，只能人工看</h2><div class="note"><ul>')
        for u in plan["unprobable"]:
            parts.append("<li><kbd>%s</kbd> %s</li>" % (esc(u["combo"]), esc(u.get("why", ""))))
        parts.append('</ul><div style="margin-top:9px">这类按键由输入法在系统层截走，'
                     '要到输入法的按键设置里关，热键工具看不见它。</div></div>')

    if plan.get("clean"):
        parts.append('<h2>空着的键</h2><div class="note">%s</div>'
                     % "、".join("<kbd>%s</kbd>" % esc(c) for c in plan["clean"]))
    if plan.get("safe_keys"):
        parts.append('<h2>要改键就往这几个上改</h2><div class="note">%s'
                     '<div style="margin-top:8px">这几组当前没有任何程序占用，'
                     '比让用户自己一个个试要快。</div></div>'
                     % "、".join("<kbd>%s</kbd>" % esc(c) for c in plan["safe_keys"]))

    parts.append('<div class="foot">方法：逐组调用系统热键注册接口试探，立即注销；'
                 '返回「已被占用」即判定为被占用。<br>'
                 '局限：只能发现走系统热键注册表登记的程序。走低级键盘钩子、驱动宏、'
                 '或自己轮询按键的程序在这里显示为空闲，需要用「退出软件后复测」或人工核查兜底。'
                 '探测结论是「这一组被占了」，不直接等于「就是某某软件占的」。<br>'
                 '本页未改动任何设置。</div>')
    parts.append('</div><script>%s</script></body></html>' % JS)
    return "".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description="渲染快捷键冲突报告")
    ap.add_argument("--plan", default="plan.json")
    ap.add_argument("--out", default="report.html")
    args = ap.parse_args(argv)
    if not os.path.isfile(args.plan):
        sys.stderr.write("plan 文件不存在: %s\n" % args.plan)
        return 2
    try:
        with open(args.plan, "r", encoding="utf-8-sig") as fh:
            plan = json.load(fh)
    except ValueError as exc:
        sys.stderr.write("plan 不是合法 JSON: %s\n" % exc)
        return 2
    page = render(plan)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page)
    print("report -> %s  %d 字节  冲突 %d"
          % (os.path.abspath(args.out), len(page.encode("utf-8")),
             plan.get("counts", {}).get("conflicts", 0)))
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
