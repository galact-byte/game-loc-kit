"""在不提供 Python PATH 的环境中验证 Windows 独立包及 GUI 翻译链路。"""
import argparse
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import struct
import tempfile
import time


def powershell(script, env):
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    executable = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    return subprocess.run([str(executable), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                          env=env, capture_output=True, timeout=40, check=True)


def capture_window(handle, destination):
    """直接渲染目标窗口，避免桌面上其他窗口遮挡截图。"""
    from PIL import Image
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.SetProcessDPIAware()
    user32.GetDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                     ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi32.CreateDIBSection.restype = wintypes.HANDLE
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi32.SelectObject.restype = wintypes.HANDLE
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    rectangle = wintypes.RECT()
    assert user32.GetWindowRect(handle, ctypes.byref(rectangle))
    width, height = rectangle.right - rectangle.left, rectangle.bottom - rectangle.top
    header = ctypes.create_string_buffer(struct.pack('<IiiHHIIiiII', 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0))
    bits = ctypes.c_void_p()
    screen = user32.GetDC(handle)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateDIBSection(screen, header, 0, ctypes.byref(bits), None, 0)
    assert bitmap and memory and bits.value
    previous = gdi32.SelectObject(memory, bitmap)
    try:
        assert user32.PrintWindow(handle, memory, 2), '无法渲染目标窗口'
        Image.frombytes('RGB', (width, height), ctypes.string_at(bits, width * height * 4), 'raw', 'BGRX').save(destination)
    finally:
        gdi32.SelectObject(memory, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(handle, screen)


def smoke(bundle, screenshot=None):
    bundle = bundle.resolve()
    cli, gui = bundle / 'glk.exe', bundle / 'glk-gui.exe'
    assert cli.is_file() and gui.is_file()
    env = dict(os.environ)
    env['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
    for name in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
        env.pop(name, None)
    env['QT_QPA_PLATFORM'] = 'windows'
    with tempfile.TemporaryDirectory(prefix='glk-smoke-', dir=bundle.parent) as folder:
        root = Path(folder)
        game, ws = root / '测试 game', root / '工作 区'
        data = game / 'www/data'
        data.mkdir(parents=True)
        (game / 'www/js').mkdir()
        (game / 'www/js/rpg_core.js').write_text('//', encoding='utf-8')
        (data / 'System.json').write_text(json.dumps({'gameTitle': 'テスト', 'terms': {}}), encoding='utf-8')
        page = {'list': [{'code': 401, 'parameters': ['こんにちは']}, {'code': 0, 'parameters': []}]}
        (data / 'Map001.json').write_text(json.dumps({'events': [None, {'pages': [page]}]}), encoding='utf-8')

        def run(*args):
            result = subprocess.run([str(cli), *map(str, args)], env=env, cwd=root,
                                    capture_output=True, timeout=30, encoding='utf-8')
            assert result.returncode == 0, result.stdout + result.stderr
            return result.stdout

        assert '多引擎游戏汉化工作流' in run('--help')
        run('--ws', ws, 'init', game)
        run('--ws', ws, 'extract')
        instructions = (ws / 'work/WORKER_INSTRUCTIONS.md').read_text(encoding='utf-8')
        assert cli.as_posix() in instructions and 'python -m gamelockit' not in instructions
        for relative in ('gamelockit/templates/ocr.ps1', 'gamelockit/templates/usage_zh.txt',
                         'gamelockit/adapters/godot4/runtime/glk_locale.gd', 'UnityPy/resources/uncompressed.tpk'):
            assert (bundle / '_internal' / relative).is_file(), relative
        env['GLK_SMOKE_CLI'], env['GLK_SMOKE_WS'] = str(cli), str(ws)
        agent = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$claim = & $env:GLK_SMOKE_CLI --ws $env:GLK_SMOKE_WS worker claim --worker worker-1 | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'claim failed' }
$task = Get-Content -Raw -Encoding UTF8 $claim.task_file | ConvertFrom-Json
$rows = @($task.items | ForEach-Object { @{id=$_.id; target='中文'} })
$path = Join-Path $env:GLK_SMOKE_WS 'submitted.json'
[IO.File]::WriteAllText($path, (@{translations=$rows} | ConvertTo-Json -Depth 10), [Text.UTF8Encoding]::new($false))
& $env:GLK_SMOKE_CLI --ws $env:GLK_SMOKE_WS worker submit --worker worker-1 --lease $task.lease --file $path
if ($LASTEXITCODE -ne 0) { throw 'submit failed' }
'''
        config = json.loads((ws / 'glk.json').read_text(encoding='utf-8'))
        config['translator'].update(command=[str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'),
                                             '-NoProfile', '-NonInteractive', '-EncodedCommand',
                                             base64.b64encode(agent.encode('utf-16le')).decode('ascii')], slots=1, max_concurrency=1)
        (ws / 'glk.json').write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
        with (root / 'gui.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([str(gui), str(ws)], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
        handle = None
        try:
            env['GLK_SMOKE_GUI_PID'] = str(process.pid)
            result = powershell(r'''
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
$deadline = [DateTime]::UtcNow.AddSeconds(25)
do {
    $process = Get-Process -Id $env:GLK_SMOKE_GUI_PID -ErrorAction Stop
    if ($process.MainWindowHandle -ne 0) {
        $root = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
        $condition = [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty, '开始翻译')
        $button = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
        if ($null -ne $button -and $button.Current.IsEnabled) {
            $pattern = $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
            $pattern.Invoke()
            Write-Output $process.MainWindowHandle.ToInt64()
            exit 0
        }
    }
    Start-Sleep -Milliseconds 200
} while ([DateTime]::UtcNow -lt $deadline)
throw 'The packaged GUI did not expose an enabled translation button'
''', env)
            handle = int(result.stdout.decode('ascii').strip())
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                assert process.poll() is None, (root / 'gui.log').read_text(encoding='utf-8')
                counts = json.loads(run('--ws', ws, 'status'))
                if counts['translated'] == 2:
                    break
                time.sleep(.3)
            assert counts['translated'] == 2, counts
            assert not counts['leased'] and not counts['pending_translation'], counts
            run('--ws', ws, 'check')
            output = root / '中文版'
            result = json.loads(run('--ws', ws, 'build', '--out', output, '--no-probe'))
            assert result['ok'] and result['original_changes'] == [], result
            assert json.loads((output / 'www/data/System.json').read_text(encoding='utf-8'))['gameTitle'] == '中文'
            assert json.loads((data / 'System.json').read_text(encoding='utf-8'))['gameTitle'] == 'テスト'
            if screenshot:
                time.sleep(1.2)
                capture_window(handle, screenshot)
            print('PASS: packaged CLI, GUI button, translation child, worker claim/submit, check and build; Python absent from child PATH')
        finally:
            if handle:
                ctypes.windll.user32.PostMessageW(handle, 0x0010, 0, 0)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--screenshot', type=Path)
    args = parser.parse_args()
    smoke(args.bundle, args.screenshot)
