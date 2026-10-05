# game-loc-kit

把日文（或其他语言）的 PC 游戏做成**简体中文独立副本**的命令行工具。原版游戏和原版存档不会被改动；生成的中文版是一个单独的文件夹，可以和原版并排放着玩。

> 翻译只用 AI（子 Agent），不调用机器翻译接口。

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
- 翻译：默认调用本机的 `pi` 命令行启动翻译子 Agent

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

## 许可

MIT。本工具不附带任何游戏内容；生成的汉化副本不代表官方汉化，原作版权归原权利人。
