"""引擎适配器接口。

每个适配器负责与引擎强相关的五件事：识别、解包、提取、注入（生成汉化副本）、启动检查。
翻译队列、审核、校验、门禁、发布全部由 core 完成，与引擎无关。
"""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Occurrence:
    source: str          # 原文
    surface: str         # 出处类别，如 json / script / scene / event:401 / asset:TextAsset
    ref: str             # 精确定位（文件 + 路径/偏移），供审核与回写
    context: str = ''    # 给审核/翻译的上下文提示（字段名、说话人键等，不放剧情）
    hint: str = 'unknown'  # 适配器对用途的结构性判断：display / protected / excluded / unknown


class Adapter:
    name = 'base'
    title = ''
    # 显示层注入：原文与判断逻辑保持原样，只在最终显示时替换。为 True 时 dual 用途可放行。
    display_layer = False
    # 引擎按系统代码页解读日文（非 Unicode 程序）：非日文系统需转区启动，见 launch.start。
    legacy_codepage = False
    # 引擎专用标记的正则（字符串），会与通用占位符一起做一致性校验。
    token_patterns = ()
    # 发布“原版”目录时排除的相对路径 glob（存档、日志、本机配置）。
    personal_data_globs = ('save/*', 'saves/*', '*.sav', '*.rpgsave', '*.rmmzsave', 'www/save/*', '*.log')
    # 引擎使用的翻译说明补充（写给翻译子 Agent，不含游戏内容）。
    translator_notes = ''

    @classmethod
    def detect(cls, game_dir: Path) -> int:
        """返回识别置信度 0–100。"""
        return 0

    def __init__(self, ws):
        self.ws = ws
        self.game = ws.game_dir
        self.options = ws.config.get('adapter', {})

    def unpack(self):
        """把需要的资源只读解出到 ws.unpacked。默认无需解包。"""

    def extract(self):
        """产出 Occurrence 序列。"""
        raise NotImplementedError

    def build(self, mapping, out_dir: Path):
        """生成独立汉化副本到 out_dir（不得修改原版目录），返回构建摘要 dict。"""
        raise NotImplementedError

    def probe(self, out_dir: Path) -> dict:
        """启动/加载检查；无法自动检查的引擎返回 {'skipped': 原因}。"""
        return {'skipped': '该引擎未实现自动启动检查，请手动启动验证'}

    def shared_save_locations(self, out_dir: Path):
        """汉化副本与原版共用、位于游戏目录之外的存档位置：[('dir', Path) | ('reg', 键)]。
        自动启动前会备份、结束后还原（见 saveguard）。"""
        return []

    def launcher(self, out_dir: Path):
        """汉化副本的启动文件相对路径（写入使用说明）。"""
        return None


def copy_tree(src: Path, dst: Path, exclude=()):
    """复制目录；拒绝写入已存在的非空目录，避免覆盖。"""
    import fnmatch
    import shutil
    src, dst = Path(src), Path(dst)
    if dst.exists() and any(dst.iterdir()):
        raise FileExistsError(f'目标目录非空，拒绝覆盖: {dst}')
    for path in sorted(src.rglob('*')):
        rel = path.relative_to(src).as_posix()
        if any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(path.name, g) for g in exclude):
            continue
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
