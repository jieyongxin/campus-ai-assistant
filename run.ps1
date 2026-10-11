# 一键启动（Windows PowerShell）：.\run.ps1
# 优先使用项目内已装好的 .libs，没有才创建虚拟环境并联网安装。
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

if (Test-Path ".libs\fastapi") {
    Write-Host "使用项目内置依赖 (.libs)" -ForegroundColor Cyan
    $env:PYTHONPATH = ".libs"
    $py = "python"
} else {
    if (-not (Test-Path ".venv")) {
        Write-Host "创建虚拟环境..." -ForegroundColor Cyan
        python -m venv .venv
    }
    $py = ".\.venv\Scripts\python.exe"
    Write-Host "安装依赖..." -ForegroundColor Cyan
    & $py -m pip install --upgrade pip -q
    & $py -m pip install -r requirements.txt -q
}

Write-Host "构建索引..." -ForegroundColor Cyan
& $py "scripts\build_index.py"

Write-Host "`n启动服务： http://127.0.0.1:8000" -ForegroundColor Green
& $py -m uvicorn app.main:app --host 0.0.0.0 --port 8000
