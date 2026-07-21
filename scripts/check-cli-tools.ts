/**
 * 命令行工具可用性检查
 * 验证 surya_ocr, whisper, python 等命令是否可用
 */

import { exec } from 'child_process';
import { promisify } from 'util';
import * as fs from 'fs';
import * as path from 'path';
import axios from 'axios';

const execAsync = promisify(exec);

interface CheckResult {
  name: string;
  type: 'http' | 'cli' | 'script';
  status: 'ok' | 'error' | 'warning';
  message: string;
  details?: any;
}

const results: CheckResult[] = [];

function logResult(result: CheckResult) {
  results.push(result);
  const icon = result.status === 'ok' ? '✅' : result.status === 'warning' ? '⚠️' : '❌';
  console.log(`${icon} ${result.name} (${result.type}): ${result.message}`);
  if (result.details) {
    console.log(`   ${JSON.stringify(result.details)}`);
  }
}

async function checkLMStudio() {
  console.log('\n1️⃣ Checking LM Studio (HTTP API)...');
  try {
    const response = await axios.get('http://localhost:1234/v1/models', { timeout: 3000 });
    const models = response.data.data || [];
    
    logResult({
      name: 'LM Studio',
      type: 'http',
      status: 'ok',
      message: `Running with ${models.length} models loaded`,
      details: { models: models.map((m: any) => m.id) },
    });
  } catch (error: any) {
    logResult({
      name: 'LM Studio',
      type: 'http',
      status: 'error',
      message: error.code === 'ECONNREFUSED' 
        ? 'Not running (start with `lms server start`)' 
        : error.message,
    });
  }
}

async function checkSuryaOCR() {
  console.log('\n2️⃣ Checking Surya OCR (CLI)...');
  try {
    const { stdout, stderr } = await execAsync('surya_ocr --help', { timeout: 5000 });
    const output = stdout + stderr;
    if (output.includes('Usage:') || output.includes('OCR')) {
      logResult({
        name: 'Surya OCR',
        type: 'cli',
        status: 'ok',
        message: 'Command available',
      });
    } else {
      throw new Error('Unexpected output');
    }
  } catch (error: any) {
    const hint = error.code === 'ENOENT' || error.message.includes('not recognized')
      ? 'Install with: pip install surya-ocr'
      : error.message;
    
    logResult({
      name: 'Surya OCR',
      type: 'cli',
      status: 'error',
      message: 'Command not found',
      details: { hint },
    });
  }
}

async function checkWhisper() {
  console.log('\n3️⃣ Checking Whisper (CLI)...');
  try {
    const { stdout } = await execAsync('whisper --help', { timeout: 5000 });
    if (stdout.includes('usage:') || stdout.includes('whisper')) {
      logResult({
        name: 'Whisper',
        type: 'cli',
        status: 'ok',
        message: 'Command available',
      });
    } else {
      throw new Error('Unexpected output');
    }
  } catch (error: any) {
    const hint = error.code === 'ENOENT' || error.message.includes('not recognized')
      ? 'Install with: pip install openai-whisper'
      : error.message;
    
    logResult({
      name: 'Whisper',
      type: 'cli',
      status: 'warning',
      message: 'Command not found (optional, debugging)',
      details: { hint },
    });
  }
}

async function checkCosyVoice() {
  console.log('\n4️⃣ Checking CosyVoice (Python script)...');
  
  // 检查脚本是否存在
  const scriptPath = path.join(__dirname, 'scripts/cosyvoice_wrapper.py');
  if (!fs.existsSync(scriptPath)) {
    logResult({
      name: 'CosyVoice Wrapper',
      type: 'script',
      status: 'error',
      message: 'Wrapper script not found',
      details: { expected: scriptPath },
    });
    return;
  }
  
  logResult({
    name: 'CosyVoice Wrapper',
    type: 'script',
    status: 'ok',
    message: 'Wrapper script exists',
  });
  
  // 允许通过环境变量覆盖，默认使用仓库相对路径
  const modelPath = process.env.COSYVOICE_MODEL_PATH
    ? path.resolve(process.env.COSYVOICE_MODEL_PATH)
    : path.resolve(__dirname, '../models/CosyVoice/CosyVoice/pretrained_models/CosyVoice2-0.5B');
  if (!fs.existsSync(modelPath)) {
    logResult({
      name: 'CosyVoice Model',
      type: 'script',
      status: 'warning',
      message: 'Model not found',
      details: { 
        expected: modelPath,
        hint: 'Download model first (see CosyVoice README)' 
      },
    });
    return;
  }
  
  logResult({
    name: 'CosyVoice Model',
    type: 'script',
    status: 'ok',
    message: 'Model directory exists',
  });
  
  // 检查 Python 是否可用
  try {
    const { stdout } = await execAsync('python --version', { timeout: 3000 });
    logResult({
      name: 'Python',
      type: 'cli',
      status: 'ok',
      message: `Python available: ${stdout.trim()}`,
    });
  } catch (error: any) {
    logResult({
      name: 'Python',
      type: 'cli',
      status: 'error',
      message: 'Python not found',
      details: { hint: 'Ensure Python is in PATH' },
    });
  }
}

async function printSummary() {
  console.log('\n' + '='.repeat(70));
  console.log('📊 Summary');
  console.log('='.repeat(70));
  
  const ok = results.filter(r => r.status === 'ok').length;
  const warning = results.filter(r => r.status === 'warning').length;
  const error = results.filter(r => r.status === 'error').length;
  
  console.log(`✅ OK: ${ok}`);
  console.log(`⚠️  Warning: ${warning}`);
  console.log(`❌ Error: ${error}`);
  
  if (error > 0) {
    console.log('\n❌ Failed checks:');
    results
      .filter(r => r.status === 'error')
      .forEach(r => {
        console.log(`  • ${r.name}: ${r.message}`);
        if (r.details?.hint) {
          console.log(`    💡 ${r.details.hint}`);
        }
      });
  }
  
  if (warning > 0) {
    console.log('\n⚠️  Warnings:');
    results
      .filter(r => r.status === 'warning')
      .forEach(r => {
        console.log(`  • ${r.name}: ${r.message}`);
      });
  }
  
  console.log('\n');
  
  return error === 0;
}

async function main() {
  console.log('🔍 Checking AI Service Dependencies\n');
  console.log('=' .repeat(70));
  
  await checkLMStudio();
  await checkSuryaOCR();
  await checkWhisper();
  await checkCosyVoice();
  
  const allOk = await printSummary();
  process.exit(allOk ? 0 : 1);
}

main().catch(error => {
  console.error('Fatal error:', error);
  process.exit(1);
});
