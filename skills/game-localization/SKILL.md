---
name: game-localization
description: Use when localizing a PC game into Simplified Chinese with game-loc-kit (glk) — starting a new game, auditing which text is safe to translate, running AI translation workers, building/verifying a Chinese copy, or packaging a release. Covers RPG Maker MV/MZ, TyranoScript, KiriKiri, Wolf RPG, Unity and Godot 4.
---

# 游戏汉化工作流（game-loc-kit）

用 `glk` 把一款游戏做成独立的简体中文副本。本 Skill 规定 Agent 的执行顺序与红线；命令细节见仓库 README，适配器细节见 docs/DEVELOPING.md。

## 红线（任何阶段都适用）

1. **对外防剧透**：进度与最终回复只报数字、阶段、问题类别；不展示人物名、地点、剧情、原文或译文。子 Agent 同样遵守。工作区文件可以含游戏内容，但不作为回复附件。
2. **只用 AI 翻译**：不调用机器翻译接口。
3. **只翻可见且不影响程序的文字**：含日文不等于能翻。代码标识、数据键、条件比较/匹配值、内部状态、资源路径、注释、调试日志一律保护；用途不确定 → `protected`。
4. **原版不改**：只在副本上构建与测试；`glk build` 前后核对原版清单，`original_changes` 必须为空。
5. **测试改档可追溯**：在游戏项目本地约定的账本记录目的、文件/槽、改动、改前备份位置、还原方法与验证结果；测试档与原进度档明确区分。
6. **不信第三方“全部完成”**：交付前按工作区数据自己重新排查。

## 流程

### 1. 识别与建工作区
```
glk detect <游戏目录>
glk --ws <工作区> init <游戏目录> [--source-lang ja] [--locale ja]
glk --ws <工作区> extract
```
工作区放仓库外。光盘版/ISO 里的日文原版本体等只能在日文环境运行的游戏，`init` 时加 `--locale ja`；拿不准就先直接启动原版看是否报错、乱码或秒退。`extract` 输出各用途数量；`pending` 条目必须经过审核。

### 2. 用途审核
`glk --ws <工作区> audit export` 生成批次与规约（`audit/AUDIT_INSTRUCTIONS.md`）。逐条查看出处，必要时打开解包文件确认字符串被谁读取：显示函数 → `display`；参与 `==`/字典键/路径/去重 → 显示层引擎可判 `dual`，否则 `protected`。写 `[{id, usage, reason}]` 后 `audit apply`。理由必须引用出处。

### 3. 翻译
`glk --ws <工作区> translate` 按 `glk.json` 的 `translator` 调度子 Agent（工作槽、最大并发、批量）。
- 并发从低往高逐步调；遇限流/上游错误时共享退避，不自行拉满。
- 怀疑并发导致慢之前，先看提交速度、错误与资源占用；还有未领取批次时加并发才有意义。
- 词表只收人物名、专名、地名；冲突进入 `glossary_conflicts`，由人或主 Agent 裁决。
- `glk status` 的队列百分比不等于全文完成率（审核还会补入条目）。

### 4. 门禁与构建
```
glk --ws <工作区> check [--deep]
glk --ws <工作区> build --out <副本目录>
```
门禁拒绝：未译、保留标记丢失、术语冲突、校验快照过期。修真实问题，不绕过；`--force-draft` 只用于自测。

### 5. 画面验证
```
glk --ws <工作区> shots --build <副本目录> --step wait:10 --step shot:标题 [--step key:enter ...] [--allow 允许原文.json]
```
- 声明了 `--locale ja`、或检测到按系统代码页存文字（`legacy_codepage`）的游戏，自动用 Locale Emulator `-runas` 启动；找不到 LEProc 直接报错，不退回直接启动。
- 截图前后自动备份并还原共享存档位置。
- 使用截图前核对时间戳/哈希，避免误用旧图；结论要基于 OCR 与亲眼看图，不凭记忆。
- 残留扫描要覆盖纯汉字的日文词，不只搜假名。
- 改了译文后，用测试存档进入该文字实际出现的场景截图核对，不只看固定巡检页。
- 系统性巡检（逐界面找漏翻/乱码）使用全局 `localization-playtest` Skill。

### 6. 发布
```
glk --ws <工作区> release --build <副本目录> --out <发布目录> [--title 名称]
```
生成 `原版/`、`汉化版/` 与中文使用说明。全文未完成时不得称为正式汉化包。发布、推送或对外分享前先取得用户批准。

## 引擎要点

| 引擎 | 注意 |
|---|---|
| Godot 4 | 显示层替换；资源可能加密并嵌在 EXE；覆盖拼接文本、自绘文本、渲染时加颜色标签/超链接的句子与全角分隔片段 |
| Unity | 显示层替换（BepInEx + XUnity）；静态扫描资源（默认开启），并可导入 XUnity 运行时捕获的文本 |
| 吉里吉里 | 补丁包方式写入；Shift-JIS 剧本会自动判定需转区 |
| Wolf 3.x | 标题不能改（存档核对用）；UTF-8 版无需转区 |
| RPG Maker / Tyrano | 直接替换数据；注意插件参数与脚本里的匹配用字符串 |

## 常见错误

| 做法 | 问题 |
|---|---|
| 看到日文就翻 | 破坏条件判断/存档匹配 |
| 用 `LEProc -run` | 无程序配置时只弹设置窗口，游戏不启动 |
| 直接启动日文原版看到乱码/报错就当编码问题修 | 先确认是否需要转区（`--locale ja`） |
| 只翻静态标签 | 动态拼接与自绘文字漏翻 |
| 在原版目录上测试 | 污染原版与玩家存档 |
