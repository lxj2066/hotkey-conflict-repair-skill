---
name: hotkey-conflict-repair-skill
display_name: "快捷键冲突修复"
display_name_en: "Hotkey Conflict Repair"
description: "Windows 快捷键冲突体检与修复：逐组试探全局热键占用，不改设置、不触发任何程序，把「按了没反应」落到具体被占的组合，给出疑似软件与关闭路径，出一张单选裁决表，修完自动复测。不触发：Mac 与 Linux、键盘硬件损坏判定、电脑卡顿与开机自启、网络故障。"
description_zh: "Windows 快捷键冲突体检与修复：逐组试探热键占用，定位到具体组合，给出疑似占用软件与关闭路径，出单选裁决表，修完复测。"
description_en: "Windows hotkey conflict checkup: probe each combo for occupancy without touching settings, name the likely owner and its disable path, emit a one-choice arbitration table and re-probe after repair."
version: 1.0.0
author: "李献杰 Lyon"
category: utility
allowed-tools: Read, Write, Edit, Bash
---

# 快捷键冲突修复

用户的真实诉求不是「让我学会排查」，是「按一下，问题就没了」。所以这个技能默认动作是**全盘速查**，输出是**一句话诊断加最少的选择**，不是一张大表。

## 触发条件

**触发**：快捷键冲突、按了没反应、截图键被抢、`Alt+A` 不好使、主面板键弹出的不是那个软件、鼠标自己打字或侧键连招、宏冲突、想查某个组合被谁占了、修完想复测。

**不触发**：macOS 或 Linux 的键位问题、判断键盘某键是否物理损坏、电脑卡顿与开机自启清理（那是 `lyon-windows-pc-doctor` 的范围）、上不了网或网速慢（Windows 网络诊断的范畴）、单纯问某个软件好不好用。

## 工作流

五步，每步都有可核对产物。阶段之间不许跳，跳了就会拿猜测当结论。

### 1 探测：先查清，再开口

```
python scripts/hk_probe.py --out probe.json
```

按 `assets/hotkey-catalog.json` 的候选组合逐组试探系统热键注册，登记后立即注销。同时看驱动软件在不在跑。

判据：输出 `probe.json`，每项状态是 `taken / free / reserved / unprobable / error` 之一，没有 `error` 才算探测完成。

要查用户点名的组合，加 `--combos "Alt+A,Ctrl+Alt+Q"`。不要全键盘暴力扫。

### 2 判定：把占用变成可执行的动作

```
python scripts/hk_plan.py --probe probe.json --out plan.json
```

判定规则写死在脚本里，不要临场改：多候选要裁决，单候选先退出复测，无候选走人工识别，系统保留键标灰。

判据：`plan.json` 里每处冲突都带 `kind`（multi / single / unknown）与 `actions`，且 `headline` 是一句能直接念给用户听的话。

### 3 出表：只在必须有人的意图时出表

```
python scripts/hk_report.py --plan plan.json --out report.html
```

报告首屏是一句话诊断，然后才是有冲突的行。三列：快捷键、保留哪个程序（单选）、当前状态。系统保留键整行标灰。

判据：`report.html` 能独立打开，且同一份 `plan.json` 渲染两次字节一致。

### 4 执行：能代劳的只有查，动手一律指路

按 `references/repair-ladder.md` 定级。改别人软件的设置、按驱动总开关、导入屏蔽规则，都由用户点，我们只把路径说到分钟级。

判据：给到用户的每一步都是「打开哪里 → 点哪一项 → 改成什么」，不是「去设置里改一下」。

### 5 复测：没复测不许说修好了

再跑一次 `scripts/hk_probe.py`，与上一次的 `probe.json` 逐项对齐。变 `free` 才说已修复；仍 `taken` 就说已释放但可能被抢回，给出永久关闭的路径。

用户做完裁决后，用 `python scripts/hk_plan.py --record "Alt+A=微信"` 把它记住，下次默认沿用它。

判据：复测结果逐项对比过，不是只看冲突总数。

## 输出契约

对外只给三档，顺序固定：

1. **一句结论**：几处被占、最要紧的那一处、要不要用户选。
2. **动作清单**：不超过 3 条，每条一行，带完整点击路径。
3. **文件**：`probe.json`、`plan.json`、`report.html` 的路径。

不写原理科普，不列全部扫描结果，不复述脚本输出。

## 红线

- 不许把「探测到被占用」说成「被某某软件占用」。归属只有退出软件复测后才能确认，其余一律说疑似。
- 不许替用户改别的软件的配置文件、注册表、驱动设置。
- 不许建议装内核驱动或注入类工具来解决一个截图键的问题。
- 不许建议卸载用户的软件、关掉安全软件来「净化环境」。
- 不许承诺「永久解决」。可以承诺「这次释放了，并给你永久关闭的路径」。
- 探测不到的一律说探测不到，不许编一条结论填坑。

## 降级

| 情况 | 处置 | 退到哪 |
|---|---|---|
| 脚本报错或 Python 不可用 | 说明未实测，改走人工核查清单 | `references/field-notes.md` 的排查顺序 |
| 没有写权限，出不了文件 | 直接把一句话结论和动作清单写在对话里 | 不进文件流程 |
| 候选库对不上占用者 | 走人工识别：按托盘逐个退出常驻软件，每退一个复测一次 | `references/field-notes.md` 第二节 |
| 用户坚持按了没反应但探测为空闲 | 说明钩子与输入法层查不到，转到输入法设置与软件自身开关 | `references/field-notes.md` 第一节 |
| 驱动宏冲突 | 只给总开关位置，不代按 | `references/repair-ladder.md` 的 L2 |
| 多个软件都该保留 | 出单选表，记录选择，修完复测 | `references/repair-ladder.md` 的 L4 |

## 自检

- [ ] 探测跑过、`error` 为零吗？没跑就写「未实测」了吗？
- [ ] 报告里每个软件名都标了「疑似」或给出了复测证据吗？
- [ ] 系统保留键有没有被当成冲突让用户去改？
- [ ] 动作清单每条都能落到「点哪里」，不是「去设置里改」吧？
- [ ] 修完复测过吗？没复测就没说「已修复」吧？
- [ ] 改过脚本后整批重跑 `python tests/run_tests.py` 了吗？

## 索引

| 要找什么 | 去哪看 |
|---|---|
| 候选组合与疑似占用者、各软件的关闭路径 | `assets/hotkey-catalog.json` |
| 五梯队排序、每类症状与归属判定的三级证据 | `references/conflict-tiers.md` |
| 四级修复阶梯的真实边界、为什么不能自动改别人软件 | `references/repair-ladder.md` |
| 误判反例、话术、不要碰的东西 | `references/field-notes.md` |
| 实机探测（会改动机器状态：只登记再注销） | `scripts/hk_probe.py` |
| 判定与修复计划 | `scripts/hk_plan.py` |
| 渲染单页报告 | `scripts/hk_report.py` |
| 包内回归用例 | `tests/run_tests.py` |
