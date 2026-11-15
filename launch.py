"""Windows 图形入口的环境检查与启动；不自动安装或修改全局环境。"""
import sys


def check_python():
    if sys.version_info < (3, 10):
        raise RuntimeError('需要 Python 3.10 或以上版本。')
    print('[OK] Python ' + sys.version.split()[0])


def check_dependencies():
    try:
        import PyQt6.QtWidgets  # noqa: F401
    except ImportError as exc:
        raise RuntimeError('当前 Python 缺少 PyQt6。请使用已安装 PyQt6 的 Python，或运行：python -m pip install -e ".[gui]"') from exc
    print('[OK] PyQt6 已就绪')


def start_app():
    from gamelockit.gui import launch
    return launch(sys.argv[1] if len(sys.argv) > 1 else None)


def main():
    try:
        check_python()
        check_dependencies()
        return start_app()
    except (ImportError, OSError, RuntimeError) as exc:
        print('[X] ' + str(exc))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
