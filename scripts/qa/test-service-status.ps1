# Test script to verify backend service status detection
Write-Host "Testing Backend Service Status Detection" -ForegroundColor Cyan

Write-Host "`n1. Testing health endpoint without refresh..." -ForegroundColor Yellow
$response1 = Invoke-RestMethod -Uri "http://localhost:3000/api/system/health" -Method Get
Write-Host "Services status (no refresh):" -ForegroundColor Green
$response1.data.services | ConvertTo-Json -Depth 3

Write-Host "`n2. Testing health endpoint WITH refresh..." -ForegroundColor Yellow
$response2 = Invoke-RestMethod -Uri "http://localhost:3000/api/system/health?refresh=true" -Method Get
Write-Host "Services status (with refresh):" -ForegroundColor Green
$response2.data.services | ConvertTo-Json -Depth 3

Write-Host "`n3. Comparing statuses..." -ForegroundColor Yellow
Write-Host "ASR Status: $($response2.data.services.asr.status)" -ForegroundColor $(if($response2.data.services.asr.status -eq 'running'){'Green'}else{'Red'})
Write-Host "TTS Status: $($response2.data.services.tts.status)" -ForegroundColor $(if($response2.data.services.tts.status -eq 'running'){'Green'}else{'Red'})
Write-Host "LLM Status: $($response2.data.services.llm.status)" -ForegroundColor $(if($response2.data.services.llm.status -eq 'running'){'Green'}else{'Red'})
Write-Host "OCR Status: $($response2.data.services.ocr.status)" -ForegroundColor $(if($response2.data.services.ocr.status -eq 'running'){'Green'}else{'Red'})

Write-Host "`n4. Testing if actual processes are running..." -ForegroundColor Yellow
$pythonProcesses = Get-Process python -ErrorAction SilentlyContinue
if ($pythonProcesses) {
    Write-Host "Python processes found:" -ForegroundColor Green
    $pythonProcesses | ForEach-Object {
        Write-Host "  PID: $($_.Id), CPU: $($_.CPU), Memory: $([math]::Round($_.WorkingSet64/1MB, 2)) MB"
    }
} else {
    Write-Host "No Python processes running!" -ForegroundColor Red
}

Write-Host "`nTest complete!" -ForegroundColor Cyan
