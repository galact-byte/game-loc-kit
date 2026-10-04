"""启动游戏、按脚本操作并截取窗口画面（Windows，ctypes；不依赖额外软件）。

用于构建后的画面检查：截图 → OCR（Windows 自带 OCR）→ 残留扫描。
按键和点击使用真实输入（部分引擎不处理投递的窗口消息），每次发送前确认游戏窗口位于前台，否则报错停止；
截图优先 PrintWindow，空白时才在确认前台后截屏，二者都得不到画面就报错而不是保存他人窗口。
操作步骤格式（字符串列表）：
  wait:秒          等待
  key:名称         按键（enter/space/esc/down/up/left/right/ctrl 或单个字符）
  click:x,y        点击（坐标为截图像素）
  shot:名称        截图保存为 名称.png
"""
import ctypes
from ctypes import wintypes
from pathlib import Path
import time

from . import launch

user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32')
kernel32 = ctypes.WinDLL('kernel32')
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetAncestor.restype = wintypes.HWND

VK = {'enter': 0x0D, 'space': 0x20, 'esc': 0x1B, 'down': 0x28, 'up': 0x26, 'left': 0x25, 'right': 0x27, 'ctrl': 0x11}
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class CaptureError(RuntimeError):
    pass


def find_window(pids):
    """返回属于这些进程、可见且面积最大的顶层窗口。"""
    best = []

    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value in pids:
                rect = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(rect))
                best.append((rect.right * rect.bottom, hwnd))
        return True
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    best.sort(reverse=True)
    return best[0][1] if best and best[0][0] > 0 else None


def _client_size(hwnd):
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    return rect.right, rect.bottom


def _client_to_screen(hwnd, x, y):
    point = wintypes.POINT(x, y)
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    return point.x, point.y


def _bring_to_front(hwnd):
    """Windows 限制后台进程抢前台；临时挂接前台线程输入队列后再切换，并回报是否成功。"""
    user32.ShowWindow(hwnd, 9)
    current = user32.GetForegroundWindow()
    if current == hwnd:
        return True
    fg_thread = user32.GetWindowThreadProcessId(current, None)
    me = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(me, fg_thread, True)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        user32.AttachThreadInput(me, fg_thread, False)
    time.sleep(0.5)
    return user32.GetAncestor(user32.GetForegroundWindow(), 2) == hwnd


def _print_window(hwnd):
    from PIL import Image
    w, h = _client_size(hwnd)
    hdc = user32.GetDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, 3)  # PW_CLIENTONLY | PW_RENDERFULLCONTENT

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG),
                    ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                    ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG),
                    ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD)]
    info = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(info), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    return Image.frombuffer('RGB', (w, h), buf, 'raw', 'BGRX', 0, 1)


def _blank(image):
    lo, hi = image.convert('L').getextrema()
    return hi - lo < 8


def grab(hwnd, path):
    """优先 PrintWindow（不会截进遮挡的其他窗口）；空白（部分硬件加速引擎）时才在确认前台后截屏。"""
    from PIL import ImageGrab
    image = _print_window(hwnd)
    if _blank(image):
        image = None
        if _bring_to_front(hwnd):
            w, h = _client_size(hwnd)
            left, top = _client_to_screen(hwnd, 0, 0)
            image = ImageGrab.grab(bbox=(left, top, left + w, top + h), all_screens=True)
            if user32.GetAncestor(user32.GetForegroundWindow(), 2) != hwnd or _blank(image):
                image = None
        if image is None:
            raise CaptureError('无法取得游戏画面（PrintWindow 为空白且窗口未能置前）')
    image.save(path)
    return path


def _ensure_front(hwnd):
    if not _bring_to_front(hwnd):
        raise CaptureError('游戏窗口无法置于前台，已停止发送输入，避免误操作其他窗口')


def press(hwnd, name):
    """真实按键：吉里吉里等引擎不处理投递的窗口消息；只在确认游戏窗口位于前台时发送。"""
    _ensure_front(hwnd)
    code = VK.get(name.lower()) or user32.VkKeyScanW(ord(name)) & 0xFF
    scan = user32.MapVirtualKeyW(code, 0)  # DirectInput 类引擎（如 WOLF）只认扫描码
    user32.keybd_event(code, scan, 0, 0)
    time.sleep(0.12)
    user32.keybd_event(code, scan, 2, 0)


def click(hwnd, x, y):
    """真实点击（坐标为截图像素，本进程已按物理像素感知 DPI）；点击后把鼠标放回原处。"""
    _ensure_front(hwnd)
    sx, sy = _client_to_screen(hwnd, x, y)
    old = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(old))
    try:
        user32.SetCursorPos(sx, sy)
        time.sleep(0.15)
        user32.mouse_event(2, 0, 0, 0, 0)
        time.sleep(0.08)
        user32.mouse_event(4, 0, 0, 0, 0)
        time.sleep(0.1)
    finally:
        user32.SetCursorPos(old.x, old.y)


def run(exe, steps, out_dir, options=None, startup_timeout=60, legacy_codepage=False):
    """启动 exe（按 launch 配置决定是否转区）并执行步骤；结束时关闭游戏进程。"""
    user32.SetProcessDPIAware()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    session, info = launch.start(exe, options, legacy_codepage=legacy_codepage)
    if session is None:
        return {'shots': [], **info}
    shots = []
    try:
        hwnd, deadline = None, time.time() + startup_timeout
        while hwnd is None and time.time() < deadline:
            time.sleep(1)
            pids = session.pids()
            if not pids and session.child.poll() is not None and time.time() > deadline - startup_timeout + 25:
                return {'shots': shots, **info, 'error': '游戏进程已退出'}
            hwnd = find_window(pids)
        if hwnd is None:
            return {'shots': shots, **info, 'error': '未找到游戏窗口'}
        for step in steps:
            kind, _, arg = step.partition(':')
            if kind == 'wait':
                time.sleep(float(arg))
            elif kind == 'key':
                press(hwnd, arg)
            elif kind == 'click':
                x, y = map(int, arg.split(','))
                click(hwnd, x, y)
            elif kind == 'shot':
                shots.append(str(grab(hwnd, out_dir / f'{arg}.png')))
            else:
                raise ValueError(f'未知步骤: {step}')
            if not user32.IsWindow(hwnd):
                return {'shots': shots, **info, 'error': f'窗口在步骤 {step} 后消失'}
        return {'shots': shots, **info}
    except CaptureError as exc:
        return {'shots': shots, **info, 'error': str(exc)}
    finally:
        session.stop()
