/**
 * @fileoverview 本地 ASR 管理器 (Local ASR Manager)
 * @description 这是桌面端本地辅助 ASR 支线，不是当前后端主语音对话链路。
 *              当前主链路 ASR 已迁移到 backend_fastapi 的 SeamlessM4T；
 *              这里仍保留 whisper.cpp server 模式，用于 Electron 本地能力或离线实验。
 */

import { ipcMain, app } from 'electron';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { spawn, ChildProcess } from 'node:child_process';
import log from 'electron-log';
import http from 'node:http';

export interface AsrResult {
  text: string;
  language?: string;
  durationMs?: number;
}

export interface AsrOptions {
  /** 目标语言代码，如 'en', 'zh', 'ja', 'auto' */
  language?: string;
  /** 使用的线程数，默认 4 */
  threads?: number;
  /** 是否启用翻译到英文 */
  translate?: boolean;
}

export class AsrManager {
  private serverPath: string;
  private modelPath: string;
  private isReady: boolean = false;
  private serverProcess: ChildProcess | null = null;
  private serverPort: number = 19090;
  private serverHost: string = '127.0.0.1';
  private serverStarting: boolean = false;

  constructor(resourcesDir?: string) {
    const baseDir = resourcesDir || this.resolveResourcesDir();
    const releaseDir = path.join(baseDir, 'Release');

    // whisper.cpp v1.8.4+ 推荐使用 whisper-server.exe 常驻服务
    const serverCandidate = path.join(releaseDir, 'whisper-server.exe');
    const cliCandidate = path.join(releaseDir, 'whisper-cli.exe');
    this.serverPath = fs.existsSync(serverCandidate) ? serverCandidate : cliCandidate;

    this.modelPath = path.join(baseDir, 'ggml-tiny.bin');

    this.validate();
  }

  private resolveResourcesDir(): string {
    const __dirname = path.dirname(fileURLToPath(import.meta.url));
    // 开发环境：从 electron/main/managers 出发，向上三级到 app/v5，再进入 resources/whisper
    const devPath = path.join(__dirname, '..', '..', '..', 'resources', 'whisper');
    if (fs.existsSync(devPath)) {
      return devPath;
    }
    // 生产环境：asar 解压后的路径
    const prodPath = path.join(process.resourcesPath, 'app.asar.unpacked', 'resources', 'whisper');
    if (fs.existsSync(prodPath)) {
      return prodPath;
    }
    // 备用路径（直接放在 resources 下）
    return path.join(process.resourcesPath, 'whisper');
  }

  private validate() {
    if (!fs.existsSync(this.serverPath)) {
      log.error('ASR server binary not found:', this.serverPath);
      this.isReady = false;
      return;
    }
    if (!fs.existsSync(this.modelPath)) {
      log.error('ASR model not found:', this.modelPath);
      this.isReady = false;
      return;
    }
    this.isReady = true;
    log.info('ASR Manager ready. Server:', this.serverPath, 'Model:', this.modelPath);
  }

  public getStatus() {
    return {
      ready: this.isReady,
      serverPath: this.serverPath,
      modelPath: this.modelPath,
      port: this.serverPort,
      running: this.serverProcess !== null && !this.serverProcess.killed,
    };
  }

  /**
   * 确保 whisper-server 常驻进程正在运行。
   * 如果未运行，则启动并等待其就绪（通过轮询 HTTP 端口）。
   */
  public async ensureServerRunning(options: { threads?: number; language?: string } = {}): Promise<void> {
    if (!this.isReady) {
      throw new Error('ASR not ready: local ASR binary or model missing.');
    }
    if (this.serverProcess && !this.serverProcess.killed) {
      const healthy = await this.pingServer(500);
      if (healthy) return;
      this.stopServer();
    }
    if (this.serverStarting) {
      for (let i = 0; i < 50; i++) {
        await delay(100);
        if (this.serverProcess && !this.serverProcess.killed) {
          const healthy = await this.pingServer(500);
          if (healthy) return;
        }
      }
      throw new Error('ASR server start timeout while waiting for another starter.');
    }

    this.serverStarting = true;
    const threads = options.threads ?? 4;
    const lang = options.language || 'auto';

    await tryKillProcessOnPort(this.serverPort);

    return new Promise((resolve, reject) => {
      const args: string[] = [
        '-m', this.modelPath,
        '--host', this.serverHost,
        '--port', String(this.serverPort),
        '-t', String(threads),
        '-l', lang,
        '-nt',
        '--no-timestamps',
      ];

      log.info('Starting whisper-server with args:', args.join(' '));
      const proc = spawn(this.serverPath, args, {
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe'],
      });

      this.serverProcess = proc;

      let stderrBuffer = '';
      proc.stderr?.on('data', (chunk: Buffer) => {
        stderrBuffer += chunk.toString('utf-8');
      });

      proc.on('error', (err) => {
        this.serverStarting = false;
        log.error('whisper-server spawn error:', err);
        reject(err);
      });

      proc.on('exit', (code) => {
        if (this.serverProcess === proc) {
          this.serverProcess = null;
        }
        if (code !== 0 && code !== null) {
          log.error('whisper-server exited with code', code, 'stderr:', stderrBuffer);
        }
      });

      const checkReady = async () => {
        for (let i = 0; i < 120; i++) {
          await delay(250);
          const ok = await this.pingServer(800);
          if (ok) {
            this.serverStarting = false;
            log.info('whisper-server is ready on port', this.serverPort);
            resolve();
            return;
          }
          if (!this.serverProcess || this.serverProcess.killed) {
            this.serverStarting = false;
            reject(new Error('whisper-server process died before becoming ready.'));
            return;
          }
        }
        this.serverStarting = false;
        reject(new Error('whisper-server start timeout after 30s.'));
      };

      void checkReady();
    });
  }

  private pingServer(timeoutMs: number): Promise<boolean> {
    return new Promise((resolve) => {
      const req = http.get(`http://${this.serverHost}:${this.serverPort}/`, { timeout: timeoutMs }, (res) => {
        resolve(res.statusCode !== undefined);
        res.resume();
      });
      req.on('error', () => resolve(false));
      req.on('timeout', () => {
        req.destroy();
        resolve(false);
      });
    });
  }

  public stopServer() {
    if (this.serverProcess) {
      try {
        this.serverProcess.kill('SIGTERM');
      } catch (e) {
        log.error('Error killing whisper-server:', e);
      }
      this.serverProcess = null;
    }
  }

  /**
   * 通过 HTTP API 对 base64 WAV 音频执行 ASR 转写。
   * 会先确保 whisper-server 已启动。
   */
  public async transcribeFromBase64(base64Wav: string, options: AsrOptions = {}): Promise<AsrResult> {
    log.info('[ASR] transcribeFromBase64 called, base64 length:', base64Wav.length, 'options:', options);
    await this.ensureServerRunning({ threads: options.threads ?? 4, language: options.language || 'auto' });

    const tmpDir = path.join(app.getPath('temp'), 'aifl-asr');
    if (!fs.existsSync(tmpDir)) {
      fs.mkdirSync(tmpDir, { recursive: true });
    }
    const tmpPath = path.join(tmpDir, `asr_${Date.now()}.wav`);

    const start = Date.now();
    try {
      const wavBytes = Buffer.from(base64Wav, 'base64');
      fs.writeFileSync(tmpPath, wavBytes);
      log.info('[ASR] wrote temp wav:', tmpPath, 'size:', wavBytes.length);

      const lang = options.language || 'auto';
      const resultText = await this.postInference(tmpPath, lang);
      const durationMs = Date.now() - start;
      log.info('[ASR] inference result:', resultText, 'durationMs:', durationMs);

      return { text: resultText, language: lang, durationMs };
    } finally {
      try {
        if (fs.existsSync(tmpPath)) {
          fs.unlinkSync(tmpPath);
        }
      } catch {}
      try {
        const files = fs.readdirSync(tmpDir);
        const now = Date.now();
        for (const f of files) {
          const p = path.join(tmpDir, f);
          try {
            const stat = fs.statSync(p);
            if (now - stat.mtimeMs > 5 * 60 * 1000) {
              fs.unlinkSync(p);
            }
          } catch {}
        }
      } catch {}
    }
  }

  private postInference(wavPath: string, language: string): Promise<string> {
    return new Promise((resolve, reject) => {
      const boundary = `----NodeFormBoundary${Date.now()}`;
      const fileData = fs.readFileSync(wavPath);

      const preamble = Buffer.from([
        `--${boundary}\r\n`,
        `Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n`,
        `Content-Type: audio/wav\r\n\r\n`,
      ].join(''), 'utf-8');

      const langPart = Buffer.from([
        `\r\n--${boundary}\r\n`,
        `Content-Disposition: form-data; name="language"\r\n\r\n`,
        `${language}\r\n`,
        `--${boundary}--\r\n`,
      ].join(''), 'utf-8');

      const body = Buffer.concat([preamble, fileData, langPart]);
      log.info('[ASR] postInference request to', `${this.serverHost}:${this.serverPort}/inference`, 'language:', language, 'body size:', body.length);

      const req = http.request(
        {
          hostname: this.serverHost,
          port: this.serverPort,
          path: '/inference',
          method: 'POST',
          headers: {
            'Content-Type': `multipart/form-data; boundary=${boundary}`,
            'Content-Length': body.length,
          },
          timeout: 30000,
        },
        (res) => {
          let data = '';
          res.on('data', (chunk) => {
            data += chunk.toString('utf-8');
          });
          res.on('end', () => {
            log.info('[ASR] postInference response status:', res.statusCode, 'data:', data);
            try {
              const parsed = JSON.parse(data);
              const raw = typeof parsed.text === 'string' ? parsed.text : '';
              const text = raw
                .replace(/\[Bell\]/gi, '')
                .replace(/\[.*?\]/g, '')
                .replace(/\(\s*\)/g, '')
                .replace(/\s+/g, ' ')
                .trim();
              resolve(text);
            } catch (e) {
              resolve(data.replace(/\[Bell\]/gi, '').replace(/\s+/g, ' ').trim());
            }
          });
        }
      );

      req.on('error', (err) => reject(err));
      req.on('timeout', () => {
        req.destroy();
        reject(new Error('ASR HTTP request timeout'));
      });

      req.write(body);
      req.end();
    });
  }

  public registerIpcHandlers() {
    ipcMain.handle('asr:transcribe-from-base64', async (_event, base64Wav: string, options?: AsrOptions) => {
      try {
        const result = await this.transcribeFromBase64(base64Wav, options);
        return { ok: true, result };
      } catch (err: any) {
        log.error('asr:transcribe-from-base64 error:', err);
        return { ok: false, error: err?.message || String(err) };
      }
    });

    ipcMain.handle('asr:status', () => {
      return this.getStatus();
    });

    ipcMain.handle('asr:stop-server', () => {
      this.stopServer();
      return { ok: true };
    });
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function tryKillProcessOnPort(port: number): Promise<void> {
  return new Promise((resolve) => {
    const find = spawn('cmd', ['/c', `for /f "tokens=5" %a in ('netstat -ano ^| findstr :${port}') do taskkill /F /PID %a`], {
      windowsHide: true,
      stdio: 'ignore',
    });
    find.on('close', () => resolve());
    find.on('error', () => resolve());
  });
}
