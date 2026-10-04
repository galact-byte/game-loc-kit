param([Parameter(Mandatory = $true)][string]$List, [Parameter(Mandatory = $true)][string]$Lang, [Parameter(Mandatory = $true)][string]$Out)
# Windows 自带 OCR（Windows.Media.Ocr）。$List：每行一个图片路径（UTF-8）；结果按行写入 $Out（JSONL）。
# 缺少该语言的 OCR 组件时直接失败，不下载任何内容。
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] > $null
[Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime] > $null
[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] > $null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime] > $null
[Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime] > $null
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetGenericArguments().Count -eq 1 -and
    $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1
function Await-Result($Operation, [Type]$Type) {
    $task = $asTask.MakeGenericMethod($Type).Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($Lang))
if ($null -eq $engine) { throw "未安装 $Lang 的 Windows OCR 语言组件" }
$writer = [System.IO.StreamWriter]::new($Out, $false, [System.Text.UTF8Encoding]::new($false))
try {
    foreach ($line in (Get-Content -LiteralPath $List -Encoding UTF8)) {
        $path = [string]$line
        if (-not $path.Trim()) { continue }
        $stream = $null; $bitmap = $null; $gray = $null
        try {
            $file = Await-Result ([Windows.Storage.StorageFile]::GetFileFromPathAsync((Resolve-Path -LiteralPath $path).Path)) ([Windows.Storage.StorageFile])
            $stream = Await-Result ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
            $decoder = Await-Result ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
            $bitmap = Await-Result ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
            $gray = [Windows.Graphics.Imaging.SoftwareBitmap]::Convert($bitmap, [Windows.Graphics.Imaging.BitmapPixelFormat]::Gray8)
            $result = Await-Result ($engine.RecognizeAsync($gray)) ([Windows.Media.Ocr.OcrResult])
            $row = @{ file = $path; lines = @($result.Lines | ForEach-Object { $_.Text }) }
        } catch {
            $row = @{ file = $path; error = $_.Exception.Message }
        } finally {
            if ($null -ne $gray) { $gray.Dispose() }
            if ($null -ne $bitmap) { $bitmap.Dispose() }
            if ($null -ne $stream) { $stream.Dispose() }
        }
        $writer.WriteLine(($row | ConvertTo-Json -Depth 4 -Compress))
    }
} finally { $writer.Dispose() }
