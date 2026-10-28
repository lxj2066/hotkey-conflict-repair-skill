# 快捷键冲突修复 · Hotkey Conflict Repair

> Windows 上「按了没反应」，绝大多数不是键盘坏了，是某个常驻软件在系统层把这组键注册走了。
> 这个 skill 把它查清、说清、指到位，但**不代改**别人的软件设置。

## 它解决什么

- 截图键按了没反应，或弹出来的不是你想用的截图工具
- 想用 IDE 补全 / 游戏技能，结果切了中英文
- 按主面板键，弹出的不是那个软件
- 鼠标自己打字、侧键触发连招
- 上次改完的键，过两周装个新软件又被抢了

## 怎么查的

逐组调用系统热键注册接口试探，紧接着立即注销：

```
RegisterHotKey(NULL, id, mods | MOD_NOREPEAT, vk)
  → 失败且 GetLastError() == 1409 (ERROR_HOTKEY_ALREADY_REGISTERED)  → 已被占用
  → 成功                                                          → 空闲，立刻 UnregisterHotKey
```

只登记再注销，**不触发任何程序、不改任何配置**，也不需要管理员权限。热键表按桌面会话共享，普通权限就能探到管理员进程注册的键。

## 三个脚本

| 命令 | 干什么 | 产出 |
|---|---|---|
| `python scripts/hk_probe.py --out probe.json` | 按候选库全量探测占用，顺带看驱动软件在不在跑 | 每项 `taken / free / reserved / unprobable / error` |
| `python scripts/hk_plan.py --probe probe.json --out plan.json` | 判定冲突类型、给修复动作、记住上次裁决 | 冲突分组 + 动作清单 + 一句话结论 |
| `python scripts/hk_report.py --plan plan.json --out report.html` | 渲染单页报告 | 一句话诊断 + 单选裁决表 + 系统保留键标灰 |

```bash
python scripts/hk_probe.py --out probe.json
python scripts/hk_plan.py --probe probe.json --out plan.json
python scripts/hk_report.py --plan plan.json --out report.html
python tests/run_tests.py        # 包内回归 10 例
```

退出码：`hk_plan` 无冲突 0 / 有冲突 1 / 输入错误 2；`hk_report` 成功 0 / 输入错误 2。同一输入必得同一输出。

## 能力边界（读之前先看这段）

| 能 | 不能 |
|---|---|
| 查出哪组键被占用 | 直接说出是哪个进程占的（只能给疑似，需退出该软件后复测确认） |
| 给出各软件关闭该键的点击路径 | 替用户改别的软件的配置、注册表、驱动设置 |
| 检测驱动软件在不在运行，给全局宏开关位置 | 代按那个开关，或读取驱动里的宏绑定 |
| 出单选裁决表并记住选择 | 在系统层释放别的进程注册的热键（需注入目标进程或内核驱动，不做） |
| 修完复测确认 | 看见走低级键盘钩子、驱动宏、输入法裸修饰键（`Ctrl+Shift`、单独 `Shift`）的占用 |

所以它自动完成「查清楚」，人工完成「点一下」。把这两件事说混，用户第一次用完就不会再用第二次。

## 目录

```
SKILL.md                      技能入口：触发条件、五步工作流、红线、降级
assets/hotkey-catalog.json    候选组合、疑似占用者、各软件的关闭路径、驱动开关位置
references/conflict-tiers.md  五梯队排序与归属判定的三级证据
references/repair-ladder.md   修复阶梯的真实边界（为什么不能自动改别人软件）
references/field-notes.md     误判反例、话术、不要碰的东西
scripts/hk_probe.py           实机探测
scripts/hk_plan.py            判定与修复计划
scripts/hk_report.py          单页报告渲染
tests/run_tests.py            正例 / 反例 / 空输入 共 10 例
```

## 安装

WorkBuddy / Claude 类技能目录：把整个仓库放进 skills 目录即可，`SKILL.md` 在根，无需再套一层。

```bash
git clone https://github.com/lxj2066/hotkey-conflict-repair-skill.git ~/.workbuddy/skills/hotkey-conflict-repair-skill
```

Windows 10 / 11，Python 3.8 以上，只用标准库。

## 质量与声明

- 技能结构体检 A/100（27 条全过），包内回归 10/10，五层可解析探针 PASS。
- 探测本身是只读动作，但会瞬时占用并释放目标组合键；它不会让任何程序执行动作。
- 本工具不采集、不上传任何数据，全部在本机完成。

## 作者

李献杰 Lyon ｜ 浙江杭州 ｜ 付费咨询 · 猎头寻访 · 招聘服务 · AI 自动化改进优化

MIT License
