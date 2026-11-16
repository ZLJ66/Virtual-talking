# ─────────────────────────────────────────────────────────────
# 安全地更新 backend/.env 中的 AI 密钥 —— 输入只留在本机文件里，
# 不会进入任何对话记录。在你自己的终端运行：
#   powershell -ExecutionPolicy Bypass -File tools\set_ai_key.ps1
# ─────────────────────────────────────────────────────────────
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$envFile  = Join-Path $repoRoot 'backend\.env'

if (-not (Test-Path $envFile)) {
    Write-Host "❌ 找不到 $envFile ——请在项目目录内运行本脚本" -ForegroundColor Red
    exit 1
}

Write-Host ''
Write-Host '═══ 更新 AI 密钥（输入不显示、不记录）═══' -ForegroundColor Cyan
Write-Host ''

function Read-Hidden([string]$label) {
    $secure = Read-Host $label -AsSecureString
    return [Net.NetworkCredential]::new('', $secure).Password
}

$key     = Read-Hidden 'API Key（直接回车=保持不变）'
$baseUrl = Read-Hidden 'Base URL（直接回车=保持不变）'
$model   = Read-Hidden '模型名（直接回车=保持不变；未知可填 qwen3.8-flash）'

# ── 逐行替换写入 .env，保留其它配置 ──
$lines = Get-Content $envFile -Encoding UTF8

function Set-EnvLine($lines, [string]$prefix, [string]$value) {
    if ([string]::IsNullOrWhiteSpace($value)) { return $lines }   # 空值不动
    $found = $false
    $out = @(foreach ($l in $lines) {
        if ($l -match "^$prefix=") { $found = $true; "$prefix=$value" } else { $l }
    })
    if (-not $found -and -not [string]::IsNullOrWhiteSpace($value)) { $out += "$prefix=$value" }
    return $out
}

$lines = Set-EnvLine $lines 'AI_API_KEY'  $key
$lines = Set-EnvLine $lines 'AI_BASE_URL' $baseUrl
$lines = Set-EnvLine $lines 'AI_MODEL'    $model

# 用 UTF-8 无 BOM 写回（BOM 会让 dotenv 认不出第一个键名）
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($envFile, [string[]]$lines, $utf8NoBom)

Write-Host ''
Write-Host "✅ 已写入 $envFile" -ForegroundColor Green

# ── 立刻验证密钥是否有效（只显示结论，不显示内容）──
$final = Get-Content $envFile -Encoding UTF8
$gKey = (($final | Where-Object { $_ -match '^AI_API_KEY=' })  -replace '^AI_API_KEY=', '').Trim()
$gUrl = (($final | Where-Object { $_ -match '^AI_BASE_URL=' })  -replace '^AI_BASE_URL=', '').Trim().TrimEnd('/')
$gModel = (($final | Where-Object { $_ -match '^AI_MODEL=' })   -replace '^AI_MODEL=', '').Trim()

Write-Host ''
Write-Host "正在验证 ${gUrl}/models …" -ForegroundColor DarkGray
try {
    $resp = Invoke-RestMethod -Uri "$gUrl/models" -Headers @{ Authorization = "Bearer $gKey" } -TimeoutSec 20
    $ids = @($resp.data | ForEach-Object { $_.id })
    Write-Host "✅ 密钥有效：服务可达，模型列表共 $($ids.Count) 个" -ForegroundColor Green
    if ($gModel) {
        if ($ids -contains $gModel) {
            Write-Host "✅ 模型名 [$gModel] 存在" -ForegroundColor Green
        } else {
            Write-Host "⚠️ 模型名 [$gModel] 不在服务列表里——把相近的名字重跑本脚本再填一次" -ForegroundColor Yellow
        }
    }
} catch {
    Write-Host "❌ 验证失败：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host '   密钥已保存，但可能已过期或粘贴不完整。' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '下一步：回到对话里说一声「填好了」。我只会重启后端并验证连通，绝不读取或显示密钥内容。' -ForegroundColor Cyan
