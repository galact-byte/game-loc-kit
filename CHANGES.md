# 修改记录 — game-loc-kit

## 2026-11-15 — Windows 独立包与 GPLv3 发布许可

### 背景与目标
- 保留 PyQt6 界面，为 Windows x64 提供无需安装 Python 的 ZIP；解压后双击 `glk-gui.exe`，同目录 `glk.exe` 供 AI 和命令行使用。
- 经维护者确认，公开版采用 `GPL-3.0-only`，允许按 GPLv3 商用、修改和再分发；保留旧版本已授予的许可权利。

### 影响与兼容性
- 不更换 Qt 绑定，不迁移工作区和译文数据；源码与 wheel 仍可按原方式运行，CLI 必装依赖仍为空。
- 统一源码和冻结程序的 CLI 路径解析，GUI 以及生成给 Agent 的指令使用同目录 EXE，不再要求用户安装 Python。
- 独立包附 Python、Qt 及其他依赖许可、精确版本和源码获取说明；Release 额外提供依赖对应源码 ZIP，项目源码包包含 Windows 打包脚本。
- 发布正文沿用维护者手改版本，仅追加 Windows 独立包与 GPLv3 说明。
- 原 v0.1.0 Release 已由维护者删除，本次按其授权重建同版本并更新标签；以后修订仍使用新版本号和标签。

### 文件与实现

| 操作 | 路径 | 说明 |
|---|---|---|
| 新增 | `gamelockit/runtime.py`、`tests/test_runtime.py` | 源码与独立包启动路径及缺失 CLI 的回归检查 |
| 修改 | `gamelockit/cli.py`、`gamelockit/gui.py` | Agent 指令与窗口启动使用统一命令 |
| 新增 | `packaging/` | 双 EXE 构建、固定依赖、许可和源码收集、实际窗口按钮冒烟 |
| 修改 | `.github/workflows/release.yml`、`MANIFEST.in` | 远端构建和验证 Windows 包，发布源码附件及校验文件 |
| 修改 | `LICENSE`、`NOTICE`、`pyproject.toml`、`README.md` | GPLv3、历史权利、下载与重建说明 |
| 修改 | `docs/releases/v0.1.0.md` | 保留维护者正文，追加本次交付内容 |

### 验证
- `python -m pytest -q --tb=short --basetemp=E:/DevData/glk-windows-tests`：46 项通过，包含冻结入口、缺失 CLI、归档路径拒绝与 Qt SPDX 许可目录采集检查。
- `python -m ruff check .`：通过；工作流内 Python 步骤语法检查通过。
- 本地构建源码包，再从解压后的源码包构建 wheel：GPL 元数据、资源、Windows 构建脚本与许可文件检查通过。
- 首次本地独立包在子进程 PATH 不含 Python 时，通过实际窗口按钮完成模拟 Agent 翻译、质量检查及副本构建；未改动原版夹具。
- 远端试构建 `43687427367` 全绿：完成 Windows 测试、双 EXE 打包、依赖对应源码收集、独立 GUI 翻译冒烟和 wheel 安装验证。
- 最终独立包与源码收集步骤的远端结果以对应 GitHub Actions 运行记录为准。

### 已知限制与后续
- 独立包不包含翻译 Agent、模型、游戏或引擎外部工具，使用者仍需配置相应环境。
- 翻译链路使用模拟 Agent 与真实进程验证；没有调用付费模型完成整款游戏翻译。
- Windows 包须完整解压，不能只移动一个 EXE；Qt 使用可替换的动态 DLL，依赖源码见同版本 Release。

## 2026-11-15 — GitHub Actions 构建与 Release

### 背景与目标
- 将 Windows 测试、源码包与 wheel 构建、安装验证和 GitHub Release 发布交给远端工作流执行。
- 每个版本使用仓库内人工编写的发布说明，包含安装方法、功能、验证范围和限制。

### 影响与兼容性
- 推送 `v*` 标签触发发布；在 Actions 页面选择分支手动运行时只构建产物，不创建 Release。
- 标签必须与 `pyproject.toml` 版本一致，且对应的 `docs/releases/v版本号.md` 必须存在、非空；测试或打包检查失败时不发布。
- 发行资产为 wheel、源码包与 SHA-256 校验文件，沿用 Python 3.10 以上的安装方式，不内置解释器、Qt 或模型。GUI 继续作为可选依赖。
- 源码包补齐 `launch.py`、`start-gui.bat`、修改记录和发布说明；wheel 与源码包均核对资源、许可与历史许可文件。
- 仅发布任务具有写入 Release 的权限；依赖的官方 Actions 固定到已核对的发行版本提交。
- CI 的 Ruff 固定为本机已验证的 `0.11.1`。首次远端构建使用 `0.17.5`，新版默认规则额外报出 74 项；固定检查工具版本以保持现有检查范围，不修改无关的引擎代码。
- 已发布版本不覆盖；后续修订使用新的包版本、说明文件和标签。不会迁移或修改用户工作区。
- 使用 `python -m build` 的标准隔离构建，按 `pyproject.toml` 安装构建后端，不依赖运行器预装 `setuptools`。

### 文件与实现

| 操作 | 路径 | 说明 |
|---|---|---|
| 新增 | `.github/workflows/release.yml` | Windows 检查与打包、仓库外安装冒烟、产物校验和标签发布 |
| 新增 | `docs/releases/v0.1.0.md` | 首次发布说明、下载方式与已知限制 |
| 新增 | `MANIFEST.in` | 将启动脚本、通知与说明纳入源码包 |
| 修改 | `README.md` | 发布包安装方式与维护者发布步骤 |

### 验证
- `python -m pytest -q --tb=short --basetemp=E:/DevData/glk-release-review/pytest`：41 项通过。
- `python -m ruff check .`、`git diff --check`：通过。
- 本地执行工作流内 Python 步骤：分支构建及正确版本标签通过，错误版本和缺少发布说明被拒绝。
- 调用 `setuptools.build_meta` 构建源码包，再从解压后的源码包构建 wheel；包内入口、模板、Godot 运行脚本、许可及双击脚本检查通过。
- wheel 安装到独立目录，从仓库外启动 CLI 和 Qt 窗口、运行并退出事件循环：通过。
- 远端的测试、构建和发布结果以对应标签的 GitHub Actions 运行记录为准。

### 已知限制与后续
- 不是独立 EXE，下载后仍需安装 Python 和所需依赖；翻译 Agent 与引擎外部工具仍由使用者配置。
- 手动选择分支构建生成的 Actions 产物保留 14 天；正式发行文件由 Release 保存。

## 2026-11-15 — PyQt6 任务进度窗口

### 背景与目标
- CLI 和结构化输出继续供 AI 调用，新增供用户查看真实进度、暂停／继续／取消翻译的窗口。
- 进度条按数据库中已放行文本计算，显示完成数、总数、百分比和剩余数；不可测量的阶段只显示处理中，不预测剩余时间。

### 影响与兼容性
- 保持现有 CLI 命令、译文数据库与工作区配置兼容；Qt 为 `gui` 可选依赖，CLI 的必装依赖仍为空。
- 新增 `glk gui`、`glk-gui` 和源码双击入口 `start-gui.bat`。已有 PyQt6 可直接运行，不自动安装软件。
- 工作区新增 `.glk/tasks/*.json` 任务记录与 `.glk/translate.lock` 运行锁；`PAUSE` 为批次级暂停请求，沿用 `STOP` 取消。翻译锁避免多个窗口重复启动调度。
- 取消停止 Agent 的子进程树，保留已提交译文并释放未提交租约；关闭窗口不停止任务。提取、构建等写文件阶段不加入强制挂起操作。
- 任务进度读取使用 SQLite 只读连接，并放在 Qt 后台线程中；损坏记录、任务异常退出、数据库临时忙和门禁失败均有对应提示。
- 升级无数据迁移。回退时停完任务，再回退新增文件与 CLI／调度接入即可；`.glk` 记录不影响旧版 CLI，残留 `PAUSE` 可按需删除，`STOP` 保留其原有语义。

### 文件与实现

| 操作 | 路径 | 说明 |
|---|---|---|
| 新增 | `gamelockit/progress.py` | 任务生命周期记录、心跳、只读进度快照、翻译互斥锁和控制标记 |
| 新增 | `gamelockit/gui.py` | PyQt6 进度窗口、后台刷新、控制、错误详情及目录入口 |
| 修改 | `gamelockit/cli.py` | 记录顶层操作状态与门禁结果，增加 GUI 入口，保持结构化输出 |
| 修改 | `gamelockit/supervisor.py` | 批次边界暂停／恢复，取消时停止子进程树并记录状态 |
| 修改 | `pyproject.toml` | 声明 Qt 可选依赖和图形命令入口 |
| 新增 | `launch.py`、`start-gui.bat` | Windows 最小引导、环境检查与错误提示 |
| 新增 | `tests/test_progress.py` | 14 个进度、控制、进程生命周期及 Qt 集成测试 |
| 修改 | `README.md` | 启动方式、进度含义、控制语义与旧版任务限制 |

### 验证
- `python -m pytest -q --tb=short --basetemp=E:/DevData/glk-gui-final-tests`：41 个测试通过，其中 14 个覆盖此次变更。
- `python -m ruff check .`：通过；`git diff --check`：通过。
- 使用真实 Python 子进程模拟翻译 Agent，验证当前批次完成后暂停、恢复剩余条目、取消并停止孙进程，以及点击 GUI 继续按钮启动 CLI 后显示完成。
- PyQt6 实际窗口在 640×620、980×760、1280×900 三档逻辑尺寸截图检查；小窗口采用滚动，阶段文字和翻译数量不被压缩裁切。测试工作区的 8／20 条正确显示为 40%。
- Windows CMD 从仓库外启动 `start-gui.bat`，实际进入并退出 Qt 事件循环；隔离模拟缺少 Qt 时返回错误码 2 并显示手动安装命令。检查 BAT 为 ASCII、UTF-8 无 BOM、CRLF。
- `python -m pip wheel --no-deps --no-build-isolation --wheel-dir E:/DevData/glk-gui-dist .`：wheel 构建成功；检查包含 GUI／进度模块、`glk-gui` 入口及 Qt 可选依赖元数据。
- 核对浅色界面主要文字的前景／背景对比度，最低为主按钮的 5.47:1。

### 已知限制与后续
- 本次没有调用真实付费模型或翻译实际游戏；控制链路使用模拟 Agent 与真实子进程验证。
- 旧版 CLI 没有任务记录，窗口可查看数量，完整阶段与控制需使用新版 CLI 启动。Agent 在 CLI 调用之外的思考与审核过程不可测量。
- 翻译比例只覆盖已放行条目，不代表整个汉化项目的完成比例；完整任务仍须由 AI 完成审核、质量校验、构建与游戏内巡检。

## 0.1.0 — 许可与商业授权边界

- 原创且有权授权的部分采用 `LicenseRef-Galact-Internal-Use-1.0`：允许合法个人及公司内部自用、免费分发；对外售卖、集成收费产品或提供直接收费的软件服务须书面授权。
- LICENSE、README、NOTICE 和 Python 包元数据同步；wheel 与源码包携带许可、通知和历史 MIT 正文，旧版权利不撤回。
- 不含本软件代码的输出不因此受软件许可限制；游戏和第三方内容仍须单独取得授权。
- 不改变 CLI 或汉化流程；v0.1.0 发行包包含上述许可文件。
