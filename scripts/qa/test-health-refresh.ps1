#!/usr/bin/env pwsh
# Test script to verify health refresh functionality

Write-Host "=== 后端服务状态刷新功能测试 ===" -ForegroundColor Cyan
Write-Host ""

# Check if backend is running
Write-Host "检查后端服务..." -ForegroundColor Yellow
try {
    $healthCheck = Invoke-WebRequest -Uri "http://localhost:3000/health" -UseBasicParsing -ErrorAction Stop
    Write-Host "✓ 后端服务正在运行" -ForegroundColor Green
} catch {
    Write-Host "✗ 后端服务未运行，请先启动后端服务" -ForegroundColor Red
    Write-Host "  运行命令: cd backend && npm start" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "测试 1: 获取缓存状态 (不带 refresh 参数)" -ForegroundColor Yellow
Write-Host "----------------------------------------"

$response1 = Invoke-RestMethod -Uri "http://localhost:3000/api/system/health" -Method Get
Write-Host "服务状态:" -ForegroundColor Cyan
$response1.data.services.PSObject.Properties | ForEach-Object {
    $name = $_.Name
    $status = $_.Value.status
    $lastCheck = $_.Value.lastCheck
    $time = if ($lastCheck) { [DateTimeOffset]::FromUnixTimeMilliseconds($lastCheck).LocalDateTime.ToString("HH:mm:ss.fff") } else { "N/A" }
    Write-Host "  $name : $status (最后检查: $time)" -ForegroundColor White
}

Write-Host ""
Write-Host "等待 2 秒..." -ForegroundColor Yellow
Start-Sleep -Seconds 2

Write-Host ""
Write-Host "测试 2: 强制刷新状态 (带 refresh=true 参数)" -ForegroundColor Yellow
Write-Host "----------------------------------------"

$response2 = Invoke-RestMethod -Uri "http://localhost:3000/api/system/health?refresh=true" -Method Get
Write-Host "服务状态:" -ForegroundColor Cyan
$response2.data.services.PSObject.Properties | ForEach-Object {
    $name = $_.Name
    $status = $_.Value.status
    $lastCheck = $_.Value.lastCheck
    $time = if ($lastCheck) { [DateTimeOffset]::FromUnixTimeMilliseconds($lastCheck).LocalDateTime.ToString("HH:mm:ss.fff") } else { "N/A" }
    Write-Host "  $name : $status (最后检查: $time)" -ForegroundColor White
}

Write-Host ""
Write-Host "=== 结果分析 ===" -ForegroundColor Cyan
Write-Host ""

$hasRefreshed = $false
$response1.data.services.PSObject.Properties | ForEach-Object {
    $name = $_.Name
    $time1 = $_.Value.lastCheck
    $time2 = $response2.data.services.$name.lastCheck
    
    if ($time2 -and $time1) {
        $diff = $time2 - $time1
        if ($diff -gt 100) {
            Write-Host "✓ $name : 状态已刷新 (时间差: ${diff}ms)" -ForegroundColor Green
            $hasRefreshed = $true
        } else {
            Write-Host "  $name : 状态未变化 (时间差: ${diff}ms)" -ForegroundColor Gray
        }
    }
}

Write-Host ""
if ($hasRefreshed) {
    Write-Host "✓ 测试通过: 刷新功能正常工作" -ForegroundColor Green
    Write-Host "  当用户点击'刷新状态'按钮时，会触发实时健康检查" -ForegroundColor Green
} else {
    Write-Host "✗ 测试失败: 刷新功能未生效" -ForegroundColor Red
    Write-Host "  可能原因: 服务已经在最近检查过，或健康检查逻辑未触发" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "测试 3: 连续调用两次刷新" -ForegroundColor Yellow
Write-Host "----------------------------------------"

$response3a = Invoke-RestMethod -Uri "http://localhost:3000/api/system/health?refresh=true" -Method Get
Start-Sleep -Milliseconds 500
$response3b = Invoke-RestMethod -Uri "http://localhost:3000/api/system/health?refresh=true" -Method Get

Write-Host "第二次刷新后的状态:" -ForegroundColor Cyan
$response3b.data.services.PSObject.Properties | ForEach-Object {
    $name = $_.Name
    $status = $_.Value.status
    Write-Host "  $name : $status" -ForegroundColor White
}

Write-Host ""
Write-Host "=== 测试完成 ===" -ForegroundColor Cyan
