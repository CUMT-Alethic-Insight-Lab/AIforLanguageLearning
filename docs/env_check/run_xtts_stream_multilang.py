#!/usr/bin/env python3
"""
XTTS v2 流式 TTS 脚本 - 支持中英日三语零样本克隆

环境变量接口（与 CosyVoice 保持一致）:
- XTTS_TEXT_ZH: 中文文本
- XTTS_TEXT_EN: 英文文本
- XTTS_TEXT_JA: 日文文本
- XTTS_LANGS: 语言列表（如 'zh,en,ja'）
- XTTS_PROMPT_WAV: 提示音频路径（零样本克隆）
- XTTS_OUT_DIR: 输出目录
- XTTS_TEMPERATURE: 采样温度（默认 0.7，范围 0.1-1.0）
- XTTS_LENGTH_PENALTY: 长度惩罚（默认 1.0）
- XTTS_REPETITION_PENALTY: 重复惩罚（默认 2.0）
- XTTS_TOP_K: Top-K 采样（默认 50）
- XTTS_TOP_P: Top-P 采样（默认 0.8）
"""

import os
import sys

# 禁用PyTorch fake tensor mode加速checkpoint加载
os.environ.setdefault('PYTORCH_FAKE_TENSOR_ENABLED', '0')
os.environ.setdefault('TORCH_LOGS', '-fake_tensor')
import time
import warnings
from pathlib import Path
from typing import List, Optional

import torch
import numpy as np
import soundfile as sf  # 替代 torchaudio
import torchaudio

# ============================================================
# Torchaudio 2.10+ 兼容性补丁 (缺少 torchcodec 时回退到 soundfile)
# ============================================================
def _patched_torchaudio_load(filepath, *args, **kwargs):
    """使用 soundfile 替代 torchaudio.load，避免 torchcodec 依赖"""
    # print(f"[PATCH] Loading audio with soundfile: {filepath}")
    data, samplerate = sf.read(filepath)
    tensor = torch.from_numpy(data)
    if tensor.ndim == 1:
        tensor = tensor.unsqueeze(0)
    else:
        tensor = tensor.transpose(0, 1)
    if tensor.dtype == torch.float64:
        tensor = tensor.float()
    return tensor, samplerate

torchaudio.load = _patched_torchaudio_load

# ============================================================
# PyTorch 2.6+ 兼容性补丁 + MelSpectrogram key修复
# ============================================================
import torch.serialization as torch_ser
_original_torch_load = torch.load

def _patched_torch_load_fix_keys(*args, **kwargs):
    """
    1. 强制 weights_only=False 以兼容 TTS 库的旧模型格式
    2. 修复 MelSpectrogram buffer key 命名（torchaudio版本差异）
    """
    kwargs['weights_only'] = False
    state_dict = _original_torch_load(*args, **kwargs)
    
    # 如果是dict且有XTTS相关的keys,修复MelSpectrogram buffer命名
    if isinstance(state_dict, dict):
        keys_to_rename = {}
        for key in list(state_dict.keys()):
            # 修复: torch_spec.1.spectrogram.window -> torch_spec.1.window
            if '.spectrogram.window' in key:
                new_key = key.replace('.spectrogram.window', '.window')
                keys_to_rename[key] = new_key
            # 修复: torch_spec.1.mel_scale.fb -> torch_spec.1.fb
            elif '.mel_scale.fb' in key:
                new_key = key.replace('.mel_scale.fb', '.fb')
                keys_to_rename[key] = new_key
        
        # 应用重命名
        for old_key, new_key in keys_to_rename.items():
            state_dict[new_key] = state_dict.pop(old_key)
        
        if keys_to_rename:
            print(f"[PATCH] 修复了 {len(keys_to_rename)} 个 MelSpectrogram buffer key")
    
    return state_dict

torch.load = _patched_torch_load_fix_keys
torch_ser.load = _patched_torch_load_fix_keys

# ============================================================
# Transformers 配置
# ============================================================
os.environ['TRANSFORMERS_NO_ADVISORY_WARNINGS'] = '1'

# 现在可以安全导入 TTS
from TTS.api import TTS
from TTS.tts.models.xtts import Xtts

# Monkeypatch XTTS to use strict=False for state_dict loading
_original_xtts_load_checkpoint = Xtts.load_checkpoint

def _patched_xtts_load_checkpoint(self, config, checkpoint_dir=None, checkpoint_path=None, vocab_path=None, eval=False, strict=True, use_deepspeed=False):
    """使用 strict=False 以忽略 MelSpectrogram buffer key 不匹配"""
    print("[PATCH] XTTS load_checkpoint with strict=False")
    return _original_xtts_load_checkpoint(self, config, checkpoint_dir, checkpoint_path, vocab_path, eval, strict=False, use_deepspeed=use_deepspeed)

Xtts.load_checkpoint = _patched_xtts_load_checkpoint

warnings.filterwarnings('ignore', category=UserWarning)
warnings.filterwarnings('ignore', category=FutureWarning)


class XTTSStreamingTTS:
    """XTTS v2 流式 TTS 引擎"""
    
    def __init__(
        self,
        model_name: str = "tts_models/multilingual/multi-dataset/xtts_v2",
        device: str = "cuda" if torch.cuda.is_available() else "cpu",
        temperature: float = 0.7,
        length_penalty: float = 1.0,
        repetition_penalty: float = 2.0,
        top_k: int = 50,
        top_p: float = 0.8,
    ):
        print(f"[XTTS] 初始化模型: {model_name}")
        print(f"[XTTS] 设备: {device.upper()}")
        
        self.device = device
        self.temperature = temperature
        self.length_penalty = length_penalty
        self.repetition_penalty = repetition_penalty
        self.top_k = top_k
        self.top_p = top_p
        
        # 加载模型
        start_time = time.time()
        self.tts = TTS(model_name).to(device)
        load_time = time.time() - start_time
        print(f"[XTTS] 模型加载完成，耗时 {load_time:.2f}s\n")
    
    def split_sentences(self, text: str, language: str) -> List[str]:
        """按标点切分句子（保留原生标点，避免过度切分）"""
        import re
        
        if language == 'zh':
            # 中文：按句号、问号、感叹号切分
            sentences = re.split(r'([。！？\n]+)', text)
        elif language == 'ja':
            # 日文：按句号、问号、感叹号切分
            sentences = re.split(r'([。！？\n]+)', text)
        else:
            # 英文：按句号、问号、感叹号切分
            sentences = re.split(r'([.!?\n]+)', text)
        
        # 合并分隔符
        result = []
        for i in range(0, len(sentences) - 1, 2):
            sentence = sentences[i] + (sentences[i + 1] if i + 1 < len(sentences) else '')
            sentence = sentence.strip()
            if sentence:
                result.append(sentence)
        
        # 如果没有标点，返回原文
        if not result:
            result = [text.strip()]
        
        return result
    
    def synthesize_streaming(
        self,
        text: str,
        language: str,
        speaker_wav: str,
        output_dir: Path,
    ) -> tuple[Path, dict]:
        """
        流式合成音频（按句子切分）
        
        Returns:
            (combined_wav_path, metrics)
        """
        print(f"[XTTS] 开始合成 ({language.upper()})")
        print(f"[XTTS] 文本: {text[:80]}{'...' if len(text) > 80 else ''}")
        print(f"[XTTS] 提示音频: {speaker_wav}")
        print(f"[XTTS] 参数: T={self.temperature}, LP={self.length_penalty}, "
              f"RP={self.repetition_penalty}, top_k={self.top_k}, top_p={self.top_p}\n")
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 切分句子
        sentences = self.split_sentences(text, language)
        print(f"[XTTS] 切分为 {len(sentences)} 个句子:")
        for i, sent in enumerate(sentences, 1):
            print(f"  [{i}/{len(sentences)}] {sent[:60]}{'...' if len(sent) > 60 else ''}")
        print()
        
        # 逐句合成
        all_wavs = []
        total_duration = 0.0
        total_synthesis_time = 0.0
        first_chunk_time = None
        sample_rate = 24000  # XTTS 默认输出采样率
        
        for i, sentence in enumerate(sentences, 1):
            sent_start = time.time()
            
            # XTTS 合成（返回的是 numpy array，24kHz）
            try:
                # 注意：XTTS API 可能抛出 torchaudio 加载错误，用 tts_to_file 规避
                temp_wav = output_dir / f"temp_sent_{i}.wav"
                self.tts.tts_to_file(
                    text=sentence,
                    speaker_wav=speaker_wav,
                    language=language,
                    file_path=str(temp_wav),
                    temperature=self.temperature,
                    length_penalty=self.length_penalty,
                    repetition_penalty=self.repetition_penalty,
                    top_k=self.top_k,
                    top_p=self.top_p,
                )
                # 读回 WAV (用 soundfile 替代 torchaudio)
                wav_data, sr = sf.read(str(temp_wav), dtype='float32')
                sample_rate = sr  # 记录采样率
                wav_tensor = torch.from_numpy(wav_data).unsqueeze(0)  # [1, T]
                temp_wav.unlink()  # 删除临时文件
            except Exception as e:
                print(f"  ⚠️  句子 {i} 合成失败: {e}")
                continue
            
            sent_time = time.time() - sent_start
            total_synthesis_time += sent_time
            
            if first_chunk_time is None:
                first_chunk_time = sent_time
            
            # 累积 tensor（wav_tensor 是 [1, T]）
            all_wavs.append(wav_tensor)
            
            duration = wav_tensor.shape[1] / sample_rate
            total_duration += duration
            
            print(f"  ✅ 句子 {i}/{len(sentences)}: {duration:.2f}s 音频，耗时 {sent_time:.2f}s "
                  f"(RTF={sent_time/duration:.3f})")
        
        if not all_wavs:
            raise RuntimeError("所有句子合成失败")
        
        # 合并所有句子
        combined_wav = torch.cat(all_wavs, dim=1).squeeze(0).numpy()  # [T]
        
        # 保存（用 soundfile 替代 torchaudio）
        output_file = output_dir / f"xtts_stream_{language}.wav"
        sf.write(
            str(output_file),
            combined_wav,
            samplerate=sample_rate,
            subtype='PCM_16',
        )
        
        # 计算指标
        avg_rtf = total_synthesis_time / total_duration if total_duration > 0 else 0
        file_size = output_file.stat().st_size / 1024  # KB
        
        metrics = {
            'total_duration': total_duration,
            'total_synthesis_time': total_synthesis_time,
            'avg_rtf': avg_rtf,
            'first_chunk_time': first_chunk_time,
            'num_sentences': len(sentences),
            'file_size_kb': file_size,
        }
        
        print(f"\n[XTTS] 合成完成:")
        print(f"  总时长: {total_duration:.2f}s")
        print(f"  合成耗时: {total_synthesis_time:.2f}s")
        print(f"  平均 RTF: {avg_rtf:.3f}")
        print(f"  首句延迟: {first_chunk_time:.2f}s")
        print(f"  文件大小: {file_size:.1f} KB")
        print(f"  输出: {output_file.absolute()}\n")
        
        return output_file, metrics


def main():
    """主流程（与 CosyVoice 脚本保持一致的接口）"""
    
    # 读取环境变量
    text_zh = os.getenv('XTTS_TEXT_ZH', '')
    text_en = os.getenv('XTTS_TEXT_EN', '')
    text_ja = os.getenv('XTTS_TEXT_JA', '')
    
    langs_str = os.getenv('XTTS_LANGS', 'zh,en,ja')
    langs = [lang.strip() for lang in langs_str.split(',') if lang.strip()]
    
    prompt_wav = os.getenv('XTTS_PROMPT_WAV', '')
    out_dir = Path(os.getenv('XTTS_OUT_DIR', './xtts_outputs'))
    
    # 可选参数
    temperature = float(os.getenv('XTTS_TEMPERATURE', '0.7'))
    length_penalty = float(os.getenv('XTTS_LENGTH_PENALTY', '1.0'))
    repetition_penalty = float(os.getenv('XTTS_REPETITION_PENALTY', '2.0'))
    top_k = int(os.getenv('XTTS_TOP_K', '50'))
    top_p = float(os.getenv('XTTS_TOP_P', '0.8'))
    
    # 检查提示音频
    if not prompt_wav or not Path(prompt_wav).exists():
        print(f"❌ 错误: 提示音频不存在或未指定: {prompt_wav}")
        sys.exit(1)
    
    # 初始化引擎
    engine = XTTSStreamingTTS(
        device="cuda" if torch.cuda.is_available() else "cpu",
        temperature=temperature,
        length_penalty=length_penalty,
        repetition_penalty=repetition_penalty,
        top_k=top_k,
        top_p=top_p,
    )
    
    # 准备测试用例
    test_cases = []
    if 'zh' in langs and text_zh:
        test_cases.append(('zh', text_zh))
    if 'en' in langs and text_en:
        test_cases.append(('en', text_en))
    if 'ja' in langs and text_ja:
        test_cases.append(('ja', text_ja))
    
    if not test_cases:
        print("❌ 错误: 没有指定任何文本")
        sys.exit(1)
    
    # 逐语言合成
    print("="*80)
    print("XTTS v2 流式 TTS 测试")
    print("="*80)
    print(f"语言: {', '.join([lang.upper() for lang, _ in test_cases])}")
    print(f"提示音频: {prompt_wav}")
    print(f"输出目录: {out_dir.absolute()}")
    print(f"温度: {temperature}, 长度惩罚: {length_penalty}, 重复惩罚: {repetition_penalty}")
    print(f"Top-K: {top_k}, Top-P: {top_p}")
    print("="*80 + "\n")
    
    for lang, text in test_cases:
        try:
            output_file, metrics = engine.synthesize_streaming(
                text=text,
                language=lang,
                speaker_wav=prompt_wav,
                output_dir=out_dir,
            )
        except Exception as e:
            print(f"❌ {lang.upper()} 合成失败: {e}\n")
            import traceback
            traceback.print_exc()
            continue
    
    print("="*80)
    print("✅ 所有任务完成")
    print("="*80)


if __name__ == '__main__':
    main()
