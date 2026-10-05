#!/usr/bin/env pwsh
# 后端管理面板 v2.0 功能验证脚本

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  后端管理面板 v2.0 完整功能验证" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

$baseUrl = "http://localhost:3000"

# 测试 1: 服务参数 API
Write-Host "测试 1: 获取服务参数配置" -ForegroundColor Yellow
Write-Host "---------------------------------------------------"
try {
    $params = Invoke-RestMethod -Uri "$baseUrl/api/system/service-params" -Method Get
    if ($params.success) {
        Write-Host "✓ 服务参数获取成功" -ForegroundColor Green
        Write-Host "  后端端口: $($params.data.backend.port)" -ForegroundColor Gray
        Write-Host "  LLM 端点: $($params.data.llm.endpoint)" -ForegroundColor Gray
        Write-Host "  模型映射数量: $($params.data.llm.models.PSObject.Properties.Count)" -ForegroundColor Gray
        Write-Host "  模型映射:" -ForegroundColor Gray
        $params.data.llm.models.PSObject.Properties | ForEach-Object {
            Write-Host "    - $($_.Name): $($_.Value)" -ForegroundColor Gray
        }
    }
} catch {
    Write-Host "✗ 失败: $($_.Exception.Message)" -ForegroundColor Red
}
Write-Host ""

# 测试 2: 高级模型加载 API
Write-Host "测试 2: 高级模型加载参数构建" -ForegroundColor Yellow
Write-Host "---------------------------------------------------"
Write-Host "参数配置:" -ForegroundColor Gray
$testParams = @{
    modelPath = "qwen/qwen3-vl-8b"
    gpu = "0.8"
    contextLength = 8192
    ttl = 600
    identifier = "test-model"
    exact = $false
    yes = $true
    estimateOnly = $false
}
$testParams.PSObject.Properties | ForEach-Object {
    Write-Host "  $($_.Name): $($_.Value)" -ForegroundColor Gray
}

Write-Host ""
Write-Host "构建的 lms load 命令参数:" -ForegroundColor Gray
$cmdArgs = @()
if ($testParams.gpu) { $cmdArgs += "--gpu $($testParams.gpu)" }
if ($testParams.contextLength) { $cmdArgs += "--context-length $($testParams.contextLength)" }
if ($testParams.ttl -gt 0) { $cmdArgs += "--ttl $($testParams.ttl)" }
if ($testParams.identifier) { $cmdArgs += "--identifier $($testParams.identifier)" }
if ($testParams.exact) { $cmdArgs += "--exact" }
if ($testParams.yes) { $cmdArgs += "-y" }
if ($testParams.estimateOnly) { $cmdArgs += "--estimate-only" }

$finalCmd = "lms load `"$($testParams.modelPath)`" $($cmdArgs -join ' ')"
Write-Host "  $finalCmd" -ForegroundColor Cyan
Write-Host ""

# 测试 3: 模型列表
Write-Host "测试 3: 模型列表查询" -ForegroundColor Yellow
Write-Host "---------------------------------------------------"
try {
    $models = Invoke-RestMethod -Uri "$baseUrl/api/system/llm/models" -Method Get
    if ($models.success) {
        Write-Host "✓ 模型列表获取成功" -ForegroundColor Green
        Write-Host "  总模型数: $($models.data.models.Count)" -ForegroundColor Gray
        Write-Host "  已加载: $($models.data.loaded.Count)" -ForegroundColor Green
        Write-Host "  可用: $($models.data.available.Count)" -ForegroundColor Cyan
        
        if ($models.data.available.Count -gt 0) {
            Write-Host "  可用模型示例:" -ForegroundColor Gray
            $models.data.available | Select-Object -First 3 | ForEach-Object {
                $size = $_.sizeBytes / 1GB
                Write-Host "    - $($_.displayName) [$($size.ToString('N1')) GB]" -ForegroundColor Cyan
            }
        }
    }
} catch {
    Write-Host "✗ 失败: $($_.Exception.Message)" -ForegroundColor Red
}
Write-Host ""

# 测试 4: 配置管理
Write-Host "测试 4: 配置管理" -ForegroundColor Yellow
Write-Host "---------------------------------------------------"
try {
    $config = Invoke-RestMethod -Uri "$baseUrl/api/system/config" -Method Get
    if ($config.success) {
        Write-Host "✓ 配置获取成功" -ForegroundColor Green
        Write-Host "  LLM 端点: $($config.data.llmEndpoint)" -ForegroundColor Gray
        Write-Host "  端口: $($config.data.port)" -ForegroundColor Gray
        
        if ($config.data.models) {
            Write-Host "  模型配置:" -ForegroundColor Gray
            $config.data.models.PSObject.Properties | ForEach-Object {
                Write-Host "    - $($_.Name): $($_.Value)" -ForegroundColor Gray
            }
        }
        
        if ($config.data.prompts) {
            Write-Host "  提示词配置:" -ForegroundColor Gray
            Write-Host "    - 基础提示词: $($config.data.prompts.PSObject.Properties.Count) 个" -ForegroundColor Gray
            if ($config.data.prompts.scenarios) {
                Write-Host "    - 场景提示词: $($config.data.prompts.scenarios.PSObject.Properties.Count) 个" -ForegroundColor Gray
            }
        }
    }
} catch {
    Write-Host "✗ 失败: $($_.Exception.Message)" -ForegroundColor Red
}
Write-Host ""

# 测试 5: 页面可访问性
Write-Host "测试 5: 页面可访问性" -ForegroundColor Yellow
Write-Host "---------------------------------------------------"
$pages = @(
    @{ name = "新管理面板 v2.0"; url = "/admin-v2.html" },
    @{ name = "旧管理面板"; url = "/admin.html" },
    @{ name = "健康检查"; url = "/api/system/health" }
)

$pages | ForEach-Object {
    try {
        $response = Invoke-WebRequest -Uri "$baseUrl$($_.url)" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            Write-Host "✓ $($_.name)" -ForegroundColor Green
        } else {
            Write-Host "⚠ $($_.name) (HTTP $($response.StatusCode))" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "✗ $($_.name): $($_.Exception.Message)" -ForegroundColor Red
    }
}
Write-Host ""

# 最终总结
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "✓ 验证完成" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "📊 管理面板功能" -ForegroundColor Yellow
Write-Host "  • 概览页面 - 服务状态监控与快速操作" -ForegroundColor Gray
Write-Host "  • 提示词管理 - 统一管理所有 AI 提示词" -ForegroundColor Gray
Write-Host "  • 服务参数管理 - 完整的参数配置可视化" -ForegroundColor Gray
Write-Host ""
Write-Host "🔧 新增 API 接口" -ForegroundColor Yellow
Write-Host "  • POST /api/system/llm/load-advanced - 高级模型加载" -ForegroundColor Gray
Write-Host "  • GET /api/system/service-params - 获取服务参数" -ForegroundColor Gray
Write-Host ""
Write-Host "🌐 访问地址" -ForegroundColor Yellow
Write-Host "  新管理面板: $baseUrl/admin-v2.html" -ForegroundColor Cyan
Write-Host "  旧管理面板: $baseUrl/admin.html" -ForegroundColor Cyan
Write-Host ""
Write-Host "📚 文档" -ForegroundColor Yellow
Write-Host "  管理面板文档: ADMIN_PANEL_V2.md" -ForegroundColor Cyan
Write-Host "  功能列表: ADMIN_PANEL_FEATURES.md" -ForegroundColor Cyan
Write-Host ""
