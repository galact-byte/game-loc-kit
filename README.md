# game-loc-kit

把日文（或其他语言）的 PC 游戏做成**简体中文独立副本**的命令行工具。原版游戏和原版存档不会被改动；生成的中文版是一个单独的文件夹，可以和原版并排放着玩。

> 翻译只用大模型（子 Agent 或直接调 API），不调用传统机器翻译接口。

## 支持的游戏引擎

| 引擎 | 怎么认出来 | 中文化方式 |
|---|---|---|
| RPG Maker MV / MZ | `www/data/` 或 `data/` 里有 `System.json` | 直接替换数据文本 |
| TyranoScript | `data/scenario/*.ks`，或打包的 `app.asar` / `package.nw` | 替换剧本文本 |
| 吉里吉里（KiriKiri / KAG） | `.xp3` 包里有剧本 | 生成补丁包 |
| Wolf RPG Editor | `Data.wolf`、`Data/*.wolf` 或解开的 `Data/BasicData/` | 替换数据文本 |
| Unity | 有 `UnityPlayer.dll` 和 `*_Data/` 目录 | 通过 BepInEx + XUnity 在显示时替换 |
| Godot 4 | 有 `.pck` 或资源打包在 EXE 里 | 在显示时替换，游戏内部原文不变 |

## 准备

- Windows 10/11，Python 3.10 以上
- 安装：在本目录运行 `pip install -e .[all]`
- 需要转区的游戏（光盘版/镜像里的日文原版本体、按 Shift-JIS 存剧本的老游戏等）：安装 [Locale Emulator](https://github.com/xupefei/Locale-Emulator)，并把 `LEProc.exe` 加入 PATH，或设置环境变量 `GLK_LOCALE_EMULATOR` 指向它
- Wolf 加密包：需要 UberWolfCli.exe（加入 PATH 或设置 `GLK_UBERWOLF`）
- Unity：游戏目录已装好 BepInEx + XUnity.AutoTranslator，或在配置中指定一份
- 翻译：默认用本机的 `pi` 命令行启动翻译子 Agent；也可以换成其他能非交互运行、能读写文件和执行命令的 Agent（建工作区时用 `--agent` 选择，见下方“换用其他 Agent”）

## 下载发布版

[GitHub Releases](https://github.com/galact-byte/game-loc-kit/releases) 提供 Windows x64 独立包、wheel、源码包及 `SHA256SUMS.txt` 校验文件。

**Windows 用户**：下载 `game-loc-kit-0.1.0-windows-x64.zip`，完整解压到可写目录，双击 `glk-gui.exe`。无需安装 Python 或 PyQt6；同目录的 `glk.exe` 是给 AI 和命令行使用的入口。请保留 `_internal` 及其他随包文件，不能只复制一个 EXE。

窗口打开后选择 AI 已建立的工作区。独立包不包含翻译模型或 Agent，也不包含游戏文件；翻译 Agent 和特定引擎的外部工具仍需另行准备。

**已有 Python 环境**：wheel 和源码包需要 Python 3.10 以上。下载 wheel 后，在下载目录运行（将文件名替换为实际版本）：

```bat
python -m pip install "game_loc_kit-0.1.0-py3-none-any.whl[all,gui]"
glk-gui
```

只用命令行可省略 `gui`；不需要 Unity／Godot 依赖时可省略 `all`。也可以解压源码包，在解压后的目录运行 `python -m pip install ".[all,gui]"`，再双击 `start-gui.bat`。

## 换用其他 Agent

翻译默认交给本机的 `pi`。想换成别的 Agent，建工作区时加 `--agent`，需要指定模型再加 `--model`，不用手写命令：

```bat
glk --ws E:/loc/某游戏 init "D:/Games/某游戏" --agent claude
glk --ws E:/loc/某游戏 init "D:/Games/某游戏" --agent codex --model gpt-6.1-sol
glk --ws E:/loc/某游戏 init "D:/Games/某游戏" --agent opencode --model opencode/big-pickle
```

- 可选 `pi`、`claude`、`codex`、`opencode`，四个预设都已在本机实测完成翻译。
- 不写 `--model` 就用该 Agent 自己的默认模型；默认模型不可用（密钥无效、上游繁忙）时，换一个能用的模型。
- 所选 Agent 要先装好、登录好，在命令行里能直接运行。
- claude、codex、opencode 的预设会跳过权限确认，子 Agent 可以在工作区里执行命令；只在你信任的环境里使用。
- 用的 Agent 不在列表里：在工作区 `glk.json` 的 `translator.command` 写完整命令，`{prompt}` 处会填入任务说明。
- 成段对话量大时，直接调用大模型 API 比子 Agent 省时间和 token：用 `glk worker claim/submit` 领取和提交，格式校验同样生效。

## 使用流程

每个游戏一个**工作区**目录（放在本仓库外面，里面有原文和译文，不要公开）。下面以 `E:/loc/某游戏` 为例：

```bat
glk detect "D:/Games/某游戏"                         :: 看看是什么引擎
glk --ws E:/loc/某游戏 init "D:/Games/某游戏"         :: 建工作区，记录原版文件清单
glk --ws E:/loc/某游戏 extract                        :: 解包并找出所有候选文字
glk --ws E:/loc/某游戏 audit export                   :: 导出待审核批次（判断哪些能翻）
glk --ws E:/loc/某游戏 translate                      :: 启动 AI 翻译
glk --ws E:/loc/某游戏 status                         :: 查看进度
glk --ws E:/loc/某游戏 check                          :: 打包前检查（漏翻、格式、术语冲突）
glk --ws E:/loc/某游戏 build --out E:/loc/某游戏/build/中文版
glk --ws E:/loc/某游戏 shots --build E:/loc/某游戏/build/中文版 --step wait:10 --step shot:标题
glk --ws E:/loc/某游戏 release --build E:/loc/某游戏/build/中文版 --out E:/loc/发布/某游戏
```

`release` 生成的目录里有 `原版/` 和 `汉化版/` 两个文件夹，以及一份中文使用说明。

## 任务进度窗口（PyQt6）

核心流程继续由 AI 调用 CLI 完成；用户可以另外打开窗口看进度、控制翻译，不必跟着读命令行。

**Windows 独立包**：双击解压目录中的 `glk-gui.exe`，无需安装依赖。

**直接使用源码**：双击本目录的 `start-gui.bat`，点击“选择工作区”，选择 AI 为这款游戏创建的、包含 `glk.json` 的文件夹。启动器使用当前 `python`，不会自动安装依赖。

已经安装工具时，也可以运行：

```bat
glk --ws E:/loc/某游戏 gui
```

`glk gui` 或 `glk-gui` 可以先打开窗口，再选择工作区。窗口需要 PyQt6；已有 PyQt6 时直接使用，缺少时可安装 `python -m pip install -e ".[gui]"`；同时需要全部引擎依赖时使用 `".[all,gui]"`。仅使用 CLI 不需要安装 Qt。

窗口每秒同步一次同一工作区的真实状态：

- 显示当前 CLI 阶段、运行状态、已耗时，以及各翻译工作进程的状态。
- 翻译进度条显示**已审核放行文本的已翻译／总数、百分比与剩余数量**；待用途审核、待复核与术语冲突另列。翻译到 100% 只代表已放行文本完成，不代表审核、构建或画面检查全部完成。
- 无法测量百分比的提取、构建、检查等阶段显示处理中动画，不估算总进度或剩余时间。
- “暂停”让当前翻译批次先完成，再停止领取；“继续翻译”恢复当前调度，或启动工作区已配置的 Agent 继续未完成条目。不同窗口共享控制状态，重复启动会被拒绝。
- “取消任务”停止翻译及其子进程，保留已提交译文，释放未提交批次；后续仍可继续。提取、构建等写文件步骤不提供强制暂停或取消。
- 展开任务记录查看错误和门禁原因，或打开日志目录查看详细日志；输出生成后可直接打开输出目录。**关闭窗口不会停止任务。**

任务记录在工作区的 `.glk/tasks/`，翻译状态与日志在 `work/worker-*/`；`PAUSE`、`STOP` 分别表示暂停与停止请求。旧版 CLI 启动的任务没有阶段记录，窗口仍能读取数量，但完整状态和控制需要使用本版本 CLI 重新启动。独立 Agent 在 CLI 命令以外的思考过程无法测量，不计为进度。

## 安全保证

- **原版不改**：`init` 记录原版每个文件的指纹，`build` 前后都会核对；中文版写到单独目录。
- **存档隔离**：中文版有自己的存档位置（引擎允许时）；`shots` 截图测试期间会先备份共享存档位置，结束后还原并核对。
- **只翻能翻的**：先做“用途审核”，代码标识、数据键、条件判断用的文字、资源路径等一律不翻；拿不准的也不翻。
- **打包门禁**：有未翻条目、变量/格式标记丢失、术语冲突或检查记录过期时，`build` 会拒绝生成（`--force-draft` 只用于测试草稿，不能发布）。

## 常见问题

**哪些游戏要转区？** 跟引擎无关，看这款游戏本身：

- 从光盘版 ISO 等渠道拿到的日文原版本体，常常只能在日文环境下启动。建工作区时加 `--locale ja`（或在 `glk.json` 设 `launch.locale` 为 `ja`），之后截图检查都会通过 Locale Emulator 启动。
- 剧本按 Shift-JIS 存储的游戏（如部分吉里吉里作品），直接打开会乱码；`glk` 会检测到并自动转区。
- 直接启动后几秒内退出的，`glk` 会自动改用转区重试。

需要转区的游戏，发布给玩家时请在说明里提示用转区方式启动。

**Wolf 3.x 的游戏标题为什么没翻？** 该引擎用标题核对存档归属，改了标题旧存档会读不出来，所以标题保持原样。

**出错时想看详细信息？** 设置环境变量 `GLK_DEBUG=1` 后重试。

## 维护者发布

版本号在 `pyproject.toml`，对应发布说明放在 `docs/releases/v版本号.md`。发布前先补齐本版本的功能、使用方法与已知限制。

`.github/workflows/release.yml` 在推送 `v*` 标签时运行：Windows 测试和代码检查 → 构建源码包、wheel 及双 EXE 独立包 → 检查资源、许可与源码说明 → 从仓库外验证安装后的 CLI／GUI → 在没有 Python PATH 的子进程中点击独立窗口并验证翻译和构建 → 生成校验文件 → 创建 GitHub Release。标签必须与包版本一致，缺少发布说明或检查失败时不会发布。发布说明直接读取版本文件，不自动生成提交列表。

独立包的依赖版本固定在 `packaging/windows-requirements.txt`；构建入口是 `packaging/windows.spec`，`packaging/prepare_windows.py` 生成随包许可和源码说明。依赖版本变化时应重新检查对应源码地址与许可证。

在 Actions 页面手动运行 `Release`、选择分支时，只构建供下载验证的工作流产物，不创建 Release。验证后再推送对应标签，例如 `git tag v0.1.0`、`git push origin v0.1.0`。同一版本不覆盖已发布资产，修订版应更新版本号和发布说明后发布新标签。

## 许可

本项目采用 **GNU GPLv3（GPL-3.0-only）**。允许商用、修改及再分发；分发软件或修改版时，须遵守 GPLv3，保留适用许可与通知，并按要求提供对应源码。软件按现状提供，不提供担保。

完整条款见 [LICENSE](LICENSE)，版权、历史许可与第三方例外见 [NOTICE](NOTICE)。此前已授予的旧版本许可权利继续有效。PyQt6、Qt 及其他依赖遵守各自许可证；Windows 包附带依赖许可、版本及源码获取说明。

本工具不附带任何游戏内容；生成的汉化副本不代表官方汉化，原作版权归原权利人。允许使用工具不等于允许销售或分发游戏及译作。
