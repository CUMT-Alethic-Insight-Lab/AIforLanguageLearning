/**
 * @fileoverview 音频管理器模块 (Audio Manager)
 * @description 负责前端音频的采集（录音）和播放。
 *              封装了 Web Audio API，提供统一的接口来处理麦克风输入流和播放后端返回的音频数据。
 *              特别处理了采样率转换（录音 16kHz，播放 24kHz）和 PCM 数据格式转换。
 */

export class AudioManager {
  // 录音相关上下文和节点
  private audioContext: AudioContext | null = null;
  private mediaStream: MediaStream | null = null;
  private scriptProcessor: ScriptProcessorNode | null = null;
  private inputSource: MediaStreamAudioSourceNode | null = null;
  
  // 播放相关上下文和状态
  private playbackContext: AudioContext | null = null;
  private nextStartTime = 0; // 下一段音频的播放起始时间，用于无缝拼接流式音频
  private activeSource: AudioBufferSourceNode | null = null;

  constructor() {
    // 初始化播放用的 AudioContext
    // XTTS 模型通常输出 24kHz 的音频，因此这里设置采样率为 24000
    const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
    this.playbackContext = new AudioContextClass({ sampleRate: 24000 });
  }

  /**
   * 开始录音
   * 
   * 请求麦克风权限，创建音频处理管道，并将采集到的 PCM 数据通过回调函数传出。
   * 
   * @param {Function} onData - 接收 PCM 音频数据 (Int16Array) 的回调函数
   * @throws {Error} 如果无法获取麦克风权限或初始化失败
   */
  async startRecording(onData: (data: Int16Array) => void) {
    try {
      // 请求用户麦克风权限，并配置音频约束
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1, // 单声道
          echoCancellation: true, // 开启回声消除
          noiseSuppression: true, // 开启降噪
          autoGainControl: true, // 开启自动增益
          sampleRate: 16000 // 录音采样率设置为 16kHz (ASR 模型推荐)
        }
      });

      // 创建录音用的 AudioContext
      const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
      this.audioContext = new AudioContextClass({ sampleRate: 16000 });

      // 创建媒体流源节点
      this.inputSource = this.audioContext.createMediaStreamSource(this.mediaStream);
      // 创建脚本处理节点 (缓冲区大小 4096, 1 输入声道, 1 输出声道)
      // 注意：ScriptProcessorNode 已废弃，建议未来迁移到 AudioWorklet
      this.scriptProcessor = this.audioContext.createScriptProcessor(4096, 1, 1);

      // 处理音频数据回调
      this.scriptProcessor.onaudioprocess = (e) => {
        const inputData = e.inputBuffer.getChannelData(0); // 获取 Float32 格式的音频数据
        const pcmData = new Int16Array(inputData.length);
        
        // 将 Float32 (-1.0 ~ 1.0) 转换为 Int16 (-32768 ~ 32767) PCM 格式
        for (let i = 0; i < inputData.length; i++) {
          let s = Math.max(-1, Math.min(1, inputData[i]));
          pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        
        // 通过回调传出 PCM 数据
        onData(pcmData);
      };

      // 连接节点：Source -> Processor -> Destination
      // 连接到 destination 是为了保证处理节点持续运行，尽管我们不直接播放录音
      this.inputSource.connect(this.scriptProcessor);
      this.scriptProcessor.connect(this.audioContext.destination);

      // 确保播放上下文处于运行状态 (某些浏览器策略需要用户交互后才能 resume)
      if (this.playbackContext?.state === 'suspended') {
        await this.playbackContext.resume();
      }

    } catch (error) {
      console.error('启动录音失败:', error);
      throw error;
    }
  }

  /**
   * 停止录音
   * 
   * 断开所有音频节点连接，关闭媒体流和 AudioContext，释放资源。
   */
  stopRecording() {
    if (this.scriptProcessor) {
      this.scriptProcessor.disconnect();
      this.scriptProcessor = null;
    }
    if (this.inputSource) {
      this.inputSource.disconnect();
      this.inputSource = null;
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach(track => track.stop());
      this.mediaStream = null;
    }
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
  }

  /**
   * 播放音频分片
   * 
   * 将 Base64 编码的 PCM 音频数据解码并播放。
   * 支持流式播放，自动计算下一段音频的播放时间以实现无缝拼接。
   * 
   * @param {string} base64Data - Base64 编码的原始 PCM 音频数据
   */
  async playChunk(base64Data: string) {
    if (!this.playbackContext) return;

    if (this.playbackContext.state === 'suspended') {
      await this.playbackContext.resume();
    }

    try {
      // 1. Base64 解码为二进制字符串
      const binaryString = atob(base64Data);
      const len = binaryString.length;
      const bytes = new Uint8Array(len);
      for (let i = 0; i < len; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }
      
      // 2. 转换为 Int16Array (假设后端发送的是 16-bit PCM)
      const int16Data = new Int16Array(bytes.buffer);
      
      // 3. 转换为 Float32Array (Web Audio API 需要)
      const float32Data = new Float32Array(int16Data.length);
      for (let i = 0; i < int16Data.length; i++) {
        float32Data[i] = int16Data[i] / 32768.0;
      }

      // 4. 创建 AudioBuffer
      const buffer = this.playbackContext.createBuffer(1, float32Data.length, 24000);
      buffer.getChannelData(0).set(float32Data);

      // 5. 创建 BufferSource 并播放
      const source = this.playbackContext.createBufferSource();
      source.buffer = buffer;
      source.connect(this.playbackContext.destination);

      // 计算播放开始时间，实现流式无缝播放
      const currentTime = this.playbackContext.currentTime;
      if (this.nextStartTime < currentTime) {
        this.nextStartTime = currentTime + 0.05; // 如果落后，稍微延迟一点播放
      }

      source.start(this.nextStartTime);
      
      // 更新下一段音频的开始时间
      this.nextStartTime += buffer.duration;
      this.activeSource = source;

    } catch (e) {
      console.error('播放音频分片失败:', e);
    }
  }

  /**
   * 播放 WAV 音频分片（后端 ws-v1 `TTS_CHUNK` 发送的是 wav bytes 的 base64）。
   */
  async playWavChunk(base64Wav: string): Promise<void> {
    if (!this.playbackContext) return;

    if (this.playbackContext.state === 'suspended') {
      await this.playbackContext.resume();
    }

    try {
      const wavBytes = base64ToUint8Array(base64Wav);
      // decodeAudioData 会解析 wav 头并返回 AudioBuffer（WebAudio 会自动重采样到 context 采样率）
      const ab = wavBytes.buffer instanceof ArrayBuffer ? wavBytes.buffer : new ArrayBuffer(wavBytes.byteLength);
      if (!(wavBytes.buffer instanceof ArrayBuffer)) {
        new Uint8Array(ab).set(wavBytes);
      }
      const audioBuffer = await this.playbackContext.decodeAudioData(ab.slice(0));

      const source = this.playbackContext.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(this.playbackContext.destination);

      const currentTime = this.playbackContext.currentTime;
      if (this.nextStartTime < currentTime) {
        this.nextStartTime = currentTime + 0.05;
      }

      source.start(this.nextStartTime);
      this.nextStartTime += audioBuffer.duration;
      this.activeSource = source;

      await new Promise<void>((resolve) => {
        source.onended = () => resolve();
      });
    } catch (e) {
      console.error('播放 WAV 分片失败:', e);
    }
  }

  /**
   * 停止播放
   *
   * 立即停止当前正在播放的音频，并重置时间戳。
   */
  stopPlayback() {
    if (this.activeSource) {
      try {
        this.activeSource.stop();
      } catch (e) {}
      this.activeSource = null;
    }
    this.nextStartTime = 0;
    if (this.playbackContext) {
      this.playbackContext.suspend();
    }
  }

  // ========== 本地 ASR + VAD 相关状态 ==========
  private asrBuffers: Int16Array[] = [];
  private asrActive: boolean = false;
  private asrSilenceFrames: number = 0;
  private asrSpeechDetected: boolean = false;
  private asrOptions: AsrRecordingOptions | null = null;
  private asrProcessing: boolean = false;

  /**
   * 开始录音并集成本地 ASR（基于能量阈值 VAD）。
   *
   * 流程：
   * 1. 持续录音，累积音频到缓冲区。
   * 2. 实时计算 RMS，判断是否处于语音段。
   * 3. 当静音持续超过阈值时，将缓冲区导出为 WAV 并调用本地 ASR。
   * 4. ASR 返回文本后，通过 onResult 回调通知调用方。
   *
   * @param options - ASR 录音配置
   */
  async startRecordingWithAsr(options: AsrRecordingOptions) {
    this.asrOptions = options;
    this.asrBuffers = [];
    this.asrActive = true;
    this.asrSilenceFrames = 0;
    this.asrSpeechDetected = false;
    this.asrProcessing = false;

    const threshold = options.speechThreshold ?? 420;
    const silenceMs = options.silenceMs ?? 700;
    const minSpeechMs = options.minSpeechMs ?? 300;

    await this.startRecording((data) => {
      if (!this.asrActive) return;

      this.asrBuffers.push(data);
      const rms = calcRms(data);
      const frameMs = (data.length / 16000) * 1000; // 16kHz sample rate

      if (rms >= threshold) {
        if (!this.asrSpeechDetected) {
          this.asrSpeechDetected = true;
          options.onVadChange?.(true);
        }
        this.asrSilenceFrames = 0;
      } else if (this.asrSpeechDetected) {
        this.asrSilenceFrames += frameMs;
      }

      const speechDurationMs = this.asrBuffers.length * frameMs - this.asrSilenceFrames;
      const shouldFinalize =
        this.asrSpeechDetected &&
        this.asrSilenceFrames >= silenceMs &&
        speechDurationMs >= minSpeechMs &&
        !this.asrProcessing;

      if (shouldFinalize) {
        this.asrProcessing = true;
        void this.finalizeAsr().then((text) => {
          if (text) {
            options.onResult?.(text);
          }
          // 清空缓冲区，准备下一轮
          this.asrBuffers = [];
          this.asrSpeechDetected = false;
          this.asrSilenceFrames = 0;
          this.asrProcessing = false;
          options.onVadChange?.(false);
        });
      }
    });
  }

  /**
   * 停止 ASR 录音。
   */
  stopRecordingWithAsr() {
    this.asrActive = false;
    this.stopRecording();
    this.asrBuffers = [];
    this.asrSpeechDetected = false;
    this.asrSilenceFrames = 0;
    this.asrProcessing = false;
  }

  // ========== 后端音频流式上传相关状态 ==========
  private backendAudioActive: boolean = false;

  /**
   * 开始录音并向后端 WebSocket 流式发送音频数据。
   *
   * 流程：
   * 1. 发送 AUDIO_START 建立请求上下文。
   * 2. 持续录音，通过 onChunk 回调将 Int16 PCM 数据发送给调用方。
   * 3. 调用方负责通过 voiceSocket 发送到后端。
   *
   * @param options - 后端音频流配置
   */
  async startRecordingForBackend(options: BackendAudioOptions) {
    this.backendAudioActive = true;

    await this.startRecording((data) => {
      if (!this.backendAudioActive) return;
      options.onChunk(data);
    });
  }

  /**
   * 停止向后端发送音频。
   */
  stopRecordingForBackend() {
    this.backendAudioActive = false;
    this.stopRecording();
  }

  /**
   * 将当前缓冲区导出为 WAV，调用 Electron 本地辅助 ASR。
   * 当前主语音对话链路仍以后端 ws-v1 + SeamlessM4T 为准。
   */
  private async finalizeAsr(): Promise<string> {
    if (!this.asrOptions || this.asrBuffers.length === 0) return '';

    const totalLen = this.asrBuffers.reduce((sum, b) => sum + b.length, 0);
    const pcm = new Int16Array(totalLen);
    let offset = 0;
    for (const b of this.asrBuffers) {
      pcm.set(b, offset);
      offset += b.length;
    }

    const wavBytes = pcm16ToWav(pcm, 16000);
    const base64Wav = arrayBufferToBase64(wavBytes.buffer as ArrayBuffer);
    console.log('[ASR] finalizeAsr called, pcm length:', pcm.length, 'base64 length:', base64Wav.length);

    try {
      const api = (window as any).api;
      if (!api?.asr?.transcribeFromBase64) {
        console.error('ASR API not available in window.api');
        return '';
      }
      const langMap: Record<string, string> = {
        'English': 'en',
        'Japanese': 'ja',
        'Chinese': 'zh',
        'French': 'fr',
      };
      const lang = langMap[this.asrOptions.language || ''] || this.asrOptions.language || 'auto';
      console.log('[ASR] calling transcribeFromBase64, lang:', lang);
      const res = await api.asr.transcribeFromBase64(base64Wav, {
        language: lang,
        threads: 4,
      });
      console.log('[ASR] transcribeFromBase64 result:', res);
      if (res?.ok) {
        return res.result?.text || '';
      } else {
        console.error('ASR error:', res?.error);
        return '';
      }
    } catch (e) {
      console.error('ASR finalize error:', e);
      return '';
    }
  }
}

export interface AsrRecordingOptions {
  language?: string;
  speechThreshold?: number;
  silenceMs?: number;
  minSpeechMs?: number;
  onVadChange?: (speaking: boolean) => void;
  onResult?: (text: string) => void;
  onError?: (err: string) => void;
}

export interface BackendAudioOptions {
  requestId: string;
  onChunk: (data: Int16Array) => void;
}

export const audioManager = new AudioManager();

function base64ToUint8Array(base64Data: string): Uint8Array {
  const binaryString = atob(base64Data);
  const len = binaryString.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes;
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function pcm16ToWav(pcmData: Int16Array, sampleRate: number): Uint8Array {
  const buffer = new ArrayBuffer(44 + pcmData.length * 2);
  const view = new DataView(buffer);

  function writeString(offset: number, str: string) {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  }

  writeString(0, 'RIFF');
  view.setUint32(4, 36 + pcmData.length * 2, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, 'data');
  view.setUint32(40, pcmData.length * 2, true);

  for (let i = 0; i < pcmData.length; i++) {
    view.setInt16(44 + i * 2, pcmData[i], true);
  }

  return new Uint8Array(buffer);
}

function calcRms(pcm: Int16Array): number {
  if (!pcm || pcm.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < pcm.length; i++) {
    const v = pcm[i];
    sum += v * v;
  }
  return Math.sqrt(sum / pcm.length);
}
