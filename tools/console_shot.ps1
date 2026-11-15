# Capture a real console-window screenshot of the weather program.
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\console_shot.ps1 `
#       -Title "WeatherLab" -RunArgs "--brief --charts --fresh" `
#       -OutPrefix "docs/screenshots/run" -WaitSec 42 -Frames 1 -WinH 1035 -Zoom 5
param(
    [string]$Title     = "WeatherLab",
    [string]$RunArgs   = "--charts",
    [string]$OutPrefix = "docs/screenshots/run",
    [int]$WaitSec      = 42,
    [int]$Frames       = 1,
    [int]$WinW         = 1360,
    [int]$WinH         = 1035,
    [int]$Zoom         = 5,
    [switch]$Diag
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

$code = @"
using System;
using System.Drawing;
using System.Runtime.InteropServices;

public class WinCap {
    [DllImport("user32.dll", CharSet=CharSet.Unicode)]
    public static extern IntPtr FindWindow(string cls, string title);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, IntPtr extra);

    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

    public static bool Place(string title, int x, int y, int w, int h) {
        IntPtr hwnd = FindWindow(null, title);
        if (hwnd == IntPtr.Zero) return false;
        ShowWindow(hwnd, 5);
        return SetWindowPos(hwnd, IntPtr.Zero, x, y, w, h, 0x0040) && SetForegroundWindow(hwnd);
    }

    public static bool Shot(string title, string outPath) {
        IntPtr hwnd = FindWindow(null, title);
        if (hwnd == IntPtr.Zero) return false;
        SetForegroundWindow(hwnd);
        System.Threading.Thread.Sleep(700);
        RECT r; GetWindowRect(hwnd, out r);
        int w = r.Right - r.Left, h = r.Bottom - r.Top;
        if (w < 100 || h < 100) return false;
        using (Bitmap bmp = new Bitmap(w, h)) {
            using (Graphics g = Graphics.FromImage(bmp)) {
                g.CopyFromScreen(r.Left, r.Top, 0, 0, new Size(w, h));
            }
            bmp.Save(outPath, System.Drawing.Imaging.ImageFormat.Png);
        }
        return true;
    }

    public static bool Exists(string title) {
        return FindWindow(null, title) != IntPtr.Zero;
    }

    // Windows Terminal zooms with Ctrl+Minus (VK_CONTROL=0x11, VK_OEM_MINUS=0xBD)
    public static void ZoomOut(string title, int times) {
        IntPtr hwnd = FindWindow(null, title);
        if (hwnd != IntPtr.Zero) SetForegroundWindow(hwnd);
        System.Threading.Thread.Sleep(400);
        for (int i = 0; i < times; i++) {
            keybd_event(0x11, 0, 0, IntPtr.Zero);
            keybd_event(0xBD, 0, 0, IntPtr.Zero);
            keybd_event(0xBD, 0, 2, IntPtr.Zero);
            keybd_event(0x11, 0, 2, IntPtr.Zero);
            System.Threading.Thread.Sleep(180);
        }
        System.Threading.Thread.Sleep(600);
    }
}
"@
Add-Type -TypeDefinition $code -ReferencedAssemblies System.Drawing

# --- launcher batch ---
$bat = Join-Path $env:TEMP ("runshot_{0}.bat" -f ([guid]::NewGuid().ToString("N").Substring(0,6)))
$lines = @(
    "@echo off",
    "chcp 65001 >nul",
    "title $Title",
    "cd /d `"$root`"",
    "timeout /t 6 /nobreak >nul",
    "python tools\console_run.py $RunArgs"
)
Set-Content -Path $bat -Value $lines -Encoding OEM

$proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "`"$bat`"" -PassThru -WindowStyle Normal

# Size the window before any real output is produced.
$placed = $false
for ($t = 0; $t -lt 60; $t++) {
    if ([WinCap]::Exists($Title)) {
        [WinCap]::Place($Title, 0, 0, $WinW, $WinH) | Out-Null
        $placed = $true
        Write-Host "window placed"
        break
    }
    Start-Sleep -Milliseconds 100
}
if (-not $placed) { Write-Host "WARN: window not found in 6s" }

# Shrink the font BEFORE python runs (the batch waits 6s), so the whole output
# is laid out at the final size and never gets re-flowed.
if ($Zoom -gt 0) {
    Start-Sleep -Milliseconds 900
    [WinCap]::ZoomOut($Title, $Zoom)
    Write-Host "zoomed out x$Zoom"
}

Write-Host "pid=$($proc.Id), waiting ${WaitSec}s ..."
Start-Sleep -Seconds $WaitSec

if (-not [WinCap]::Exists($Title)) {
    Write-Host "ERROR: window '$Title' not found"
    try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
    Remove-Item $bat -Force -ErrorAction SilentlyContinue
    exit 1
}

$dir = Split-Path -Parent (Join-Path $root "$OutPrefix.png")
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

[WinCap]::Place($Title, 0, 0, $WinW, $WinH) | Out-Null
# Let Windows Terminal finish its smooth-scroll animation before grabbing pixels
Start-Sleep -Milliseconds 2600

for ($i = 0; $i -lt $Frames; $i++) {
    $outPath = Join-Path $root ("{0}_{1}.png" -f $OutPrefix, $i)
    $ok = [WinCap]::Shot($Title, $outPath)
    if ($ok) {
        Write-Host ("frame{0} -> {1} ({2:N0} KB)" -f $i, $outPath, ((Get-Item $outPath).Length/1KB))
    } else {
        Write-Host ("frame{0} FAILED" -f $i)
    }
    if ($i -lt $Frames - 1) { Start-Sleep -Milliseconds 700 }
}

# cleanup
Start-Sleep -Milliseconds 300
try { Get-Process -Id $proc.Id -ErrorAction SilentlyContinue | Stop-Process -Force } catch {}
Get-Process -Name python -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -like "*$Title*" } |
    ForEach-Object { try { Stop-Process -Id $_.Id -Force } catch {} }
Get-Process -Name conhost -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -like "*$Title*" } |
    ForEach-Object { try { Stop-Process -Id $_.Id -Force } catch {} }
Remove-Item $bat -Force -ErrorAction SilentlyContinue
Write-Host "done"

