# Service Status Refresh Test Script
# 测试后端管理面板刷新时是否正确更新服务状态

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "服务状态刷新测试" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$backendUrl = "http://localhost:3000"
$healthEndpoint = "$backendUrl/api/system/health"

# 测试函数：获取服务状态
function Get-ServiceStatus {
    param(
        [bool]$Refresh = $false
    )
    
    try {
        $url = $healthEndpoint
        if ($Refresh) {
            $url = "$healthEndpoint`?refresh=true"
            Write-Host "📡 请求服务状态 (带刷新): $url" -ForegroundColor Yellow
        } else {
            Write-Host "📡 请求服务状态 (缓存): $url" -ForegroundColor Gray
        }
        
        $response = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 10
        
        if ($response.success) {
            Write-Host "✅ 请求成功" -ForegroundColor Green
            return $response.data
        } else {
            Write-Host "❌ 请求失败: $($response.message)" -ForegroundColor Red
            return $null
        }
    } catch {
        Write-Host "❌ 请求异常: $_" -ForegroundColor Red
        return $null
    }
}

# 显示服务状态
function Show-ServiceStatus {
    param($Data, $Label)
    
    Write-Host "`n=== $Label ===" -ForegroundColor Cyan
    Write-Host "时间戳: $($Data.timestamp)" -ForegroundColor Gray
    Write-Host ""
    
    foreach ($service in $Data.services.PSObject.Properties) {
        $name = $service.Name
        $info = $service.Value
        
        $statusColor = switch ($info.status) {
            "running" { "Green" }
            "stopped" { "Red" }
            "error" { "Magenta" }
            default { "Gray" }
        }
        
        Write-Host "  [$name]" -ForegroundColor White -NoNewline
        Write-Host " 状态: " -NoNewline
        Write-Host "$($info.status)" -ForegroundColor $statusColor -NoNewline
        Write-Host " | 最后检查: $($info.lastCheck)" -NoNewline
        Write-Host " | 错误次数: $($info.errorCount)" -ForegroundColor Yellow
    }
}

# 比较两次状态
function Compare-ServiceStatus {
    param($Before, $After)
    
    Write-Host "`n=== 状态变化分析 ===" -ForegroundColor Magenta
    
    $changed = $false
    
    foreach ($service in $After.services.PSObject.Properties) {
        $name = $service.Name
        $afterInfo = $service.Value
        $beforeInfo = $Before.services.$name
        
        if (-not $beforeInfo) {
            Write-Host "  [$name] 新增服务" -ForegroundColor Yellow
            $changed = $true
            continue
        }
        
        # 检查状态是否改变
        if ($beforeInfo.status -ne $afterInfo.status) {
            Write-Host "  [$name] 状态变化: $($beforeInfo.status) -> $($afterInfo.status)" -ForegroundColor Yellow
            $changed = $true
        }
        
        # 检查 lastCheck 时间戳是否更新
        if ($beforeInfo.lastCheck -ne $afterInfo.lastCheck) {
            $timeDiff = $afterInfo.lastCheck - $beforeInfo.lastCheck
            Write-Host "  [$name] 检查时间更新: +${timeDiff}ms" -ForegroundColor Cyan
            $changed = $true
        }
        
        # 检查错误计数是否改变
        if ($beforeInfo.errorCount -ne $afterInfo.errorCount) {
            Write-Host "  [$name] 错误计数变化: $($beforeInfo.errorCount) -> $($afterInfo.errorCount)" -ForegroundColor Red
            $changed = $true
        }
    }
    
    if (-not $changed) {
        Write-Host "  ⚠️ 警告: 没有检测到任何状态变化！" -ForegroundColor Red
        Write-Host "  这可能表明刷新功能未正常工作。" -ForegroundColor Red
    } else {
        Write-Host "  ✅ 检测到状态更新" -ForegroundColor Green
    }
    
    return $changed
}

# 主测试流程
Write-Host "步骤 1: 获取初始服务状态 (不刷新)" -ForegroundColor Cyan
Write-Host "----------------------------------------" -ForegroundColor Gray
$status1 = Get-ServiceStatus -Refresh $false
if (-not $status1) {
    Write-Host "❌ 无法获取初始状态，测试中止" -ForegroundColor Red
    exit 1
}
Show-ServiceStatus -Data $status1 -Label "初始状态 (缓存)"

Write-Host "`n等待 2 秒..." -ForegroundColor Gray
Start-Sleep -Seconds 2

Write-Host "`n步骤 2: 再次获取服务状态 (不刷新)" -ForegroundColor Cyan
Write-Host "----------------------------------------" -ForegroundColor Gray
$status2 = Get-ServiceStatus -Refresh $false
if (-not $status2) {
    Write-Host "❌ 无法获取第二次状态，测试中止" -ForegroundColor Red
    exit 1
}
Show-ServiceStatus -Data $status2 -Label "第二次状态 (缓存)"

Write-Host "`n等待 2 秒..." -ForegroundColor Gray
Start-Sleep -Seconds 2

Write-Host "`n步骤 3: 获取服务状态 (带刷新)" -ForegroundColor Cyan
Write-Host "----------------------------------------" -ForegroundColor Gray
$status3 = Get-ServiceStatus -Refresh $true
if (-not $status3) {
    Write-Host "❌ 无法获取刷新后状态，测试中止" -ForegroundColor Red
    exit 1
}
Show-ServiceStatus -Data $status3 -Label "刷新后状态"

# 分析结果
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "测试结果分析" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

Write-Host "`n比较 1 vs 2 (两次缓存请求):" -ForegroundColor White
$changed_1_2 = Compare-ServiceStatus -Before $status1 -After $status2

Write-Host "`n比较 2 vs 3 (缓存 vs 刷新):" -ForegroundColor White
$changed_2_3 = Compare-ServiceStatus -Before $status2 -After $status3

# 最终结论
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "最终结论" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

if ($changed_2_3) {
    Write-Host "✅ 测试通过: 刷新功能正常工作" -ForegroundColor Green
    Write-Host "   当请求带有 refresh=true 参数时，服务状态会被重新检查并更新。" -ForegroundColor Green
    exit 0
} else {
    Write-Host "❌ 测试失败: 刷新功能可能存在问题" -ForegroundColor Red
    Write-Host "   预期: 带刷新参数的请求应该更新服务状态" -ForegroundColor Red
    Write-Host "   实际: 状态没有发生变化" -ForegroundColor Red
    Write-Host ""
    Write-Host "可能的原因:" -ForegroundColor Yellow
    Write-Host "  1. healthCheckAll() 方法未被正确调用" -ForegroundColor Yellow
    Write-Host "  2. 服务状态检查逻辑存在问题" -ForegroundColor Yellow
    Write-Host "  3. 所有服务状态已经是最新的（罕见情况）" -ForegroundColor Yellow
    exit 1
}
