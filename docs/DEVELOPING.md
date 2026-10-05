# 开发者指南

面向维护者与新引擎适配器作者。使用说明见根目录 README。

## 结构

```
gamelockit/
  cli.py          glk 命令入口（init/extract/audit/worker/translate/check/build/shots/release）
  project.py      工作区与 glk.json 默认配置
  catalog.py      SQLite 目录库：条目、出处、用途、译文、租约、词表与冲突
  supervisor.py   翻译调度：固定工作槽 + 最大并发 + 限流共享退避
  quality.py      打包门禁（未译、格式标记、术语冲突、原版指纹、校验快照）
  validate.py     译文与原文的保留标记比对
  integrity.py    原版文件清单记录与核对
  launch.py       启动：直接 / Locale Emulator 转区（-runas GUID）
  capture.py      按 PID 找窗口、向窗口发送输入、截图
  ocr.py          Windows OCR（templates/ocr.ps1）
  saveguard.py    截图测试期间备份/还原共享存档位置（目录与注册表）
  release.py      生成 原版/ 与 汉化版/ 分发目录
  formats/        纯格式读写（无引擎策略）：xp3、tjs、kag、asar、wolf
  adapters/       引擎适配器：定位、解包、提取、构建、探测、存档位置
                  godot4/ 自带 pck、gdscript、settings 与运行时脚本 runtime/
tests/            单元测试（pytest）；e2e_real.py 与 pseudo_translate.py 为真实游戏自测脚本
```

## 适配器约定（adapters/base.py）

| 成员 | 作用 |
|---|---|
| `detect(game_dir) -> 0..100` | 识别置信度；只读文件头/目录，不解包大文件 |
| `display_layer` | True 表示显示时替换（Godot/Unity），允许 `dual` 用途 |
| `legacy_codepage` | 这款游戏按系统代码页解码日文（可按游戏判断，如吉里吉里检测无 BOM 的 Shift-JIS 脚本、Wolf 检测非 UTF-8 数据）；非日文系统自动转区 |
| `token_patterns` | 必须原样保留的引擎标记正则（变量、控制符、标签） |
| `personal_data_globs` | 原版清单中排除的存档/日志，避免玩家游玩导致误报 |
| `translator_notes` | 写入翻译规约的引擎特有说明 |
| `unpack()` / `extract()` | 解包到工作区；产出 `Occurrence(source, surface, ref, context)` |
| `build(mapping, out_dir)` | 把 `{原文: 译文}` 写入**副本**；不得写原版目录 |
| `probe(out_dir)` | 构建后的启动检查 |
| `shared_save_locations(out_dir)` | 副本与原版可能共用的存档位置，供 saveguard 备份还原 |
| `launcher(out_dir)` | 副本启动文件 |

新增引擎：在 `formats/` 写纯格式读写并配往返测试 → 在 `adapters/` 写适配器 → 用 `@register` 装饰并把模块名加入 `adapters/__init__.py` 的 `MODULES` → 用真实游戏跑一次端到端。

## 已知引擎约束

- Wolf 3.x 用标题字符串核对存档归属，标题不能翻译。UTF-8 版直接启动即可显示简体中文并自动回退缺字。
- 是否转区按游戏而定，不按引擎：光盘版等只能在日文环境运行的本体用 `init --locale ja` 或 `launch.locale = "ja"` 显式声明；`auto` 只能识别代码页乱码和启动秒退两种情况。
- Locale Emulator 的 `-run` 读取目标程序自己的转区配置，没有配置时只弹出设置窗口；必须用 `-runas <GUID>`（取 LEConfig.xml 中不需要管理员权限的 ja-JP 配置）。找不到时报错，不退回直接启动。
- Godot 显示层替换要覆盖拼接文本、自绘文本、渲染时插入颜色标签的句子，以及用全角空格/全角冒号分隔的片段。
- Godot 可能把 `custom_user_dir_name` 指向与其他游戏共用的目录，存档保护按实际配置取路径。

## 测试

```bat
python -m pytest -q
ruff check .
```

真实游戏端到端自测（只在测试副本上运行，原版不改；用伪译文把假名替换为“中”，纯汉字条目前缀“中”）：

```bat
python tests/e2e_real.py <游戏目录> <工作区> --wait 25 [--pending-as display] [--step key:enter --step shot:名称]
```

输出 JSON 包含提取统计、构建摘要、启动探测、截图 OCR 与残留扫描、原版文件变动列表（必须为空）。
`--pending-as display` 只用于显示层引擎的渲染覆盖自测，不代表真实审核结论。

## 仓库卫生

工作区、截图、OCR 结果、目录库都含游戏原文或译文，只能放在仓库外；`.gitignore` 额外屏蔽了 `*.sqlite3`、`glk.json` 等。
提交前确认 `git status` 中没有游戏文本或图片。
