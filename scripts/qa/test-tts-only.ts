/**
 * 单独测试 TTS 服务
 */

import { ServiceManager } from './src/managers/service-manager';
import * as fs from 'fs';
import * as path from 'path';

async function testTTS() {
  console.log('🔊 Testing TTS Service...\n');
  
  const sm = new ServiceManager();
  await sm.initialize();
  
  try {
    console.log('Generating speech for: "Hello, this is a test of CosyVoice2 zero-shot synthesis."');
    const result = await sm.invokeTTS('Hello, this is a test of CosyVoice2 zero-shot synthesis.');
    
    const outputPath = path.join(__dirname, 'test-tts-output.wav');
    fs.writeFileSync(outputPath, result.audio);
    
    console.log('✅ TTS completed successfully!');
    console.log(`   Output: ${outputPath}`);
    console.log(`   Audio size: ${result.audio.length} bytes`);
  } catch (error: any) {
    console.error('❌ TTS Error:', error.message);
    console.error('Stack:', error.stack);
  }
}

testTTS().catch(error => {
  console.error('Fatal error:', error);
  process.exit(1);
});
