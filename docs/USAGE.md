# 使用指南

本文面向操作 game-loc-kit 的 AI 助手，以及需要自行运行命令的用户。项目介绍和 Windows 下载入口见 [README](../README.md)；审核与翻译的执行规约见 [AI 操作规约](https://github.com/galact-byte/game-loc-kit/blob/main/skills/game-localization/SKILL.md)。

## 环境与外部工具

Windows 独立包完整解压后即可运行，无需安装 Python 或 PyQt6。它不包含游戏、翻译模型、Agent 或下列引擎外部工具。

| 使用场景 | 准备内容 |
|---|---|
| 子 Agent 翻译 | 安装并登录 `pi`、`claude`、`codex` 或 `opencode`，确保对应命令可以直接运行 |
| 需要转区的日文游戏 | 安装 [Locale Emulator](https://github.com/xupefei/Locale-Emulator)，将 `LEProc.exe` 加入 PATH，或设置 `GLK_LOCALE_EMULATOR` 指向它 |
| Wolf 加密包 | 将 `UberWolfCli.exe` 加入 PATH，或设置 `GLK_UBERWOLF` 指向它 |
| Unity | 在游戏目录准备 BepInEx + XUnity.AutoTranslator，或在工作区配置中指定一份 |

并非所有游戏都需要转区，具体判断见本文常见问题。

### 从源码安装

需要 Python 3.10 以上。在源码目录运行：

```bat
python -m pip install ".[all,gui]"
glk-gui
```

仅使用命令行可省略 `gui`；不需要 Unity／Godot 依赖时可省略 `all`。开发时可用 `python -m pip install -e ".[all,gui]"` 安装可编辑版本。

源码目录中的 `start-gui.bat` 也可启动窗口。它使用当前 `python`，不会自动安装依赖。CLI 不依赖 Qt；窗口需要 PyQt6。

## 选择翻译 Agent

默认使用 `pi`。创建工作区时用 `--agent` 选择已安装、已登录的 Agent，不需要手写启动命令：

```bat
glk --ws "E:/loc/我的游戏" init "D:/Games/我的游戏" --agent claude
```

可选值为 `pi`、`claude`、`codex`、`opencode`。需要指定模型时再加 `--model`，模型名应以所选 Agent 实际可用的配置为准；不指定则使用该 Agent 的默认模型。

- 子 Agent 可以读写文件、执行命令。Claude、Codex、OpenCode 的预设会跳过交互式权限确认；Codex 预设还会关闭审批和沙箱。只在可信环境中使用。
- 若所需 Agent 不在预设中，可在工作区 `glk.json` 的 `translator.command` 写完整命令模板，`{prompt}` 会被替换为任务说明。
- 也可以直接调用大模型 API，通过 `worker claim` / `worker submit` 领取和提交批次，格式校验照常生效。工具不内置模型服务；批处理分工和提交要求见 AI 操作规约。

## 命令行流程

每款游戏使用独立工作区，放在游戏目录和工具仓库之外。工作区包含原文、译文、截图与任务数据库，不要公开上传。

以下示例使用 `glk`。Windows 独立包中请由 AI 使用 `glk.exe` 的完整路径调用；源码安装后可直接使用 `glk`。

### 1. 识别、创建工作区、提取

```bat
glk detect "D:/Games/我的游戏"
glk --ws "E:/loc/我的游戏" init "D:/Games/我的游戏" --agent pi
glk --ws "E:/loc/我的游戏" extract
```

`init` 记录原版文件清单，并生成工作区配置。原文默认按日文处理，其他语言用 `--source-lang` 指定；已知只能在日文环境运行的游戏用 `--locale ja`。

### 2. 审核哪些文字可以翻译

```bat
glk --ws "E:/loc/我的游戏" audit export
```

**导出不等于审核完成。** AI 需要读取工作区 `audit/AUDIT_INSTRUCTIONS.md` 和导出的批次，逐条根据出处判断用途，必要时查看解包文件。代码标识、资源路径、条件匹配值等不能直接翻译；不确定时予以保护。

将审核结论写成 JSON 数组，每项包含 `id`、`usage`、`reason`，再应用结论；下面的文件名为示例，需由 AI 先创建：

```bat
glk --ws "E:/loc/我的游戏" audit apply "E:/loc/我的游戏/audit/decisions.json"
```

用途取值、判断依据和结论格式以工作区规约为准；所有批次都应完成审核。

### 3. 翻译与检查

```bat
glk --ws "E:/loc/我的游戏" translate
glk --ws "E:/loc/我的游戏" status
glk --ws "E:/loc/我的游戏" check
```

`translate` 启动已配置的翻译子 Agent；使用 API 批处理时按 AI 操作规约领取和提交，不需要同时启动另一份翻译调度。

检查未通过时应修正真实问题，不得放宽校验。`--force-draft` 仅用于生成测试草稿，不能用于正式交付。

### 4. 构建与画面验证

```bat
glk --ws "E:/loc/我的游戏" build --out "E:/loc/我的游戏/build/中文版"
glk --ws "E:/loc/我的游戏" shots --build "E:/loc/我的游戏/build/中文版" --step wait:10 --step shot:标题
```

`shots` 会启动副本、截图并通过 OCR 扫描残留原文。示例只检查启动画面，**不代表已检查整款游戏**。AI 还应进入实际菜单、对话等场景，结合截图检查漏翻、乱码与排版；修改后回到对应场景复验。

### 5. 整理交付目录

确认质量及分发权限后，再运行：

```bat
glk --ws "E:/loc/我的游戏" release --build "E:/loc/我的游戏/build/中文版" --out "E:/loc/发布/我的游戏"
```

默认生成 `原版/`、`汉化版/` 和中文使用说明；不需要附带原版时可加 `--no-original`。生成目录不等于获准对外分发，游戏和译作的权利需另行确认。

## 任务进度窗口

Windows 独立包双击 `glk-gui.exe`。源码安装后可运行：

```bat
glk-gui
```

也可直接指定工作区：

```bat
glk --ws "E:/loc/我的游戏" gui
```

在窗口内选择 AI 创建的、包含 `glk.json` 的工作区文件夹。窗口是同一任务状态的视图，不是另一个独立的汉化流程。

| 操作或显示 | 含义 |
|---|---|
| 翻译进度 | 已审核放行文本中的已翻译数、总数、百分比与剩余数；待审核、待复核和术语冲突另列 |
| 提取、构建等阶段 | 显示真实运行状态；无法测量时显示处理中，不估算百分比或剩余时间 |
| 暂停 | 当前批次完成后停止领取新批次 |
| 继续翻译 | 恢复当前调度，或启动已配置的 Agent 继续未完成条目；重复启动会被拒绝 |
| 取消任务 | 终止翻译及其子进程，保留已提交译文，释放未提交批次；之后可继续 |
| 关闭窗口 | 不停止后台任务 |

提取、构建等写文件步骤不提供强制暂停或取消。翻译到 100% 不代表审核、构建或画面验证全部完成。

窗口每秒同步状态，可展开任务记录查看错误和阻止构建的原因，也可打开日志目录；有输出后可打开输出目录。

### 排查状态与日志

- 任务记录位于工作区 `.glk/tasks/`。
- 翻译状态和日志位于 `work/worker-*/`；`PAUSE`、`STOP` 分别表示暂停和停止请求。
- 旧版 CLI 启动的任务没有阶段记录，窗口仍可读取数量，但完整状态与控制需要本版本 CLI 启动的任务。
- AI 在工具命令以外的思考过程无法测量，不计为进度。

## 常见问题

### 哪些游戏需要转区？

取决于游戏本身，而非单看引擎。

- 部分光盘版或 ISO 中的日文原版本体只能在日文环境启动。建工作区时加 `--locale ja`，或在 `glk.json` 设置 `launch.locale` 为 `ja`，之后工具截图检查会通过 Locale Emulator 启动。
- 部分老游戏按 Shift-JIS 等系统代码页存储剧本，工具检测到这类依赖时会自动转区。
- 直接启动后几秒内退出的，工具会尝试转区重试；自动识别不能覆盖所有情况。

需要转区的游戏，交付说明中也应提醒玩家以转区方式启动。

### Wolf 3.x 的游戏标题为什么保持原文？

该引擎用标题核对存档归属，修改后旧存档可能无法读取，因此不翻译标题。

### 翻译完成，为什么仍不能构建？

翻译进度只统计已审核放行的文本。请查看 `check` 输出或窗口任务记录，确认是否仍有待审核、未翻译、格式标记丢失、术语冲突或校验记录过期的问题。

### 如何查看详细错误？

设置环境变量 `GLK_DEBUG=1` 后重试。分享日志前先检查是否包含游戏内容、个人路径或凭据，不要公开上传整个工作区。
