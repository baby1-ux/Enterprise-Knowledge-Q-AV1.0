# dev.ps1 — 一键启动前后端开发服务（Windows / PowerShell）
#
# 用法：
#   .\scripts\dev.ps1                # 启动后端（8000）+ 前端（5173），各开一个新窗口
#   .\scripts\dev.ps1 -BackendOnly   # 仅启动后端
#   .\scripts\dev.ps1 -FrontendOnly  # 仅启动前端
#   .\scripts\dev.ps1 -Demo          # 后端使用演示模式（SQLite + 内存向量库，无需 Docker）
#   .\scripts\dev.ps1 -Install       # 启动前先安装/更新依赖（uv sync + npm install）
#
# 前置条件：Python >= 3.10、Node >= 18；生产模式还需 Docker 启动 MySQL 与 Milvus。

param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$Demo,
    [switch]$Install
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Write-Step($message) {
    Write-Host "==> $message" -ForegroundColor Cyan
}

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

# ---------- 环境检查 ----------
if (-not (Test-Path $VenvPython)) {
    Write-Host "[X] 未找到虚拟环境 .venv，请先执行：uv sync --extra dev --no-install-project" -ForegroundColor Red
    exit 1
}
if (-not $FrontendOnly -and -not (Test-Command "uvicorn")) {
    # uvicorn 不在 PATH 属正常（装在 .venv 内），此处仅确认 Python 可用
    & $VenvPython --version | Out-Null
}

$startBackend = -not $FrontendOnly
$startFrontend = -not $BackendOnly

# ---------- 依赖安装（可选） ----------
if ($Install) {
    if ($startBackend) {
        Write-Step "安装后端依赖（uv sync --extra dev）"
        Push-Location $ProjectRoot
        try { uv sync --extra dev --no-install-project } finally { Pop-Location }
    }
    if ($startFrontend) {
        Write-Step "安装前端依赖（npm install）"
        Push-Location (Join-Path $ProjectRoot "frontend")
        try { npm install } finally { Pop-Location }
    }
}

# ---------- 启动后端 ----------
if ($startBackend) {
    if ($Demo) {
        Write-Step "启动后端（演示模式：SQLite + 内存向量库）http://127.0.0.1:8000"
        $backendArgs = "scripts\dev_local.py"
    }
    else {
        Write-Step "启动后端（生产模式：MySQL + Milvus）http://127.0.0.1:8000"
        $backendArgs = "run.py"
    }
    Start-Process -FilePath $VenvPython -ArgumentList $backendArgs -WorkingDirectory $ProjectRoot -WindowStyle Normal
}

# ---------- 启动前端 ----------
if ($startFrontend) {
    $frontendDir = Join-Path $ProjectRoot "frontend"
    if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
        Write-Step "首次运行，安装前端依赖（npm install）"
        Push-Location $frontendDir
        try { npm install } finally { Pop-Location }
    }
    Write-Step "启动前端 http://127.0.0.1:5173"
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm run dev" -WorkingDirectory $frontendDir -WindowStyle Normal
}

Write-Host ""
Write-Host "服务已在新窗口中启动：" -ForegroundColor Green
if ($startBackend) { Write-Host "  后端      : http://127.0.0.1:8000/docs" }
if ($startFrontend) { Write-Host "  前端      : http://127.0.0.1:5173" }
Write-Host "关闭对应的命令行窗口即可停止服务。" -ForegroundColor DarkGray
