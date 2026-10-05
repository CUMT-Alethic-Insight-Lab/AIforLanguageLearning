import sys
import os
import json
import time
import base64
import torch
import numpy as np
import soundfile as sf
import warnings

# ============================================================
# Torchaudio Patch
# ============================================================
import torchaudio
def _patched_torchaudio_load(filepath, *args, **kwargs):
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
# PyTorch Patch
# ============================================================
import torch.serialization as torch_ser
_original_torch_load = torch.load
def _patched_torch_load_fix_keys(*args, **kwargs):
    kwargs['weights_only'] = False
    state_dict = _original_torch_load(*args, **kwargs)
    if isinstance(state_dict, dict):
        keys_to_rename = {}
        for key in list(state_dict.keys()):
            if '.spectrogram.window' in key:
                new_key = key.replace('.spectrogram.window', '.window')
                keys_to_rename[key] = new_key
            elif '.mel_scale.fb' in key:
                new_key = key.replace('.mel_scale.fb', '.fb')
                keys_to_rename[key] = new_key
        for old_key, new_key in keys_to_rename.items():
            state_dict[new_key] = state_dict.pop(old_key)
    return state_dict
torch.load = _patched_torch_load_fix_keys
torch_ser.load = _patched_torch_load_fix_keys

# ============================================================
# TTS Imports
# ============================================================
os.environ['TRANSFORMERS_NO_ADVISORY_WARNINGS'] = '1'
from TTS.api import TTS
from TTS.tts.models.xtts import Xtts

# Monkeypatch XTTS load
_original_xtts_load_checkpoint = Xtts.load_checkpoint
def _patched_xtts_load_checkpoint(self, config, checkpoint_dir=None, checkpoint_path=None, vocab_path=None, eval=False, strict=True, use_deepspeed=False):
    return _original_xtts_load_checkpoint(self, config, checkpoint_dir, checkpoint_path, vocab_path, eval, strict=False, use_deepspeed=use_deepspeed)
Xtts.load_checkpoint = _patched_xtts_load_checkpoint

warnings.filterwarnings('ignore')

class XTTSStreamingService:
    def __init__(self):
        try:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            model_name = "tts_models/multilingual/multi-dataset/xtts_v2"
            sys.stderr.write(f"[TTS] Loading {model_name} on {self.device}...\n")
            self.tts = TTS(model_name).to(self.device)
            sys.stderr.write("[TTS] Model loaded. Ready for JSON requests via stdin.\n")
            
            # Default params
            self.temperature = 0.7
            self.length_penalty = 1.0
            self.repetition_penalty = 2.0
            self.top_k = 50
            self.top_p = 0.8
        except Exception as e:
            sys.stderr.write(f"[TTS] Init Error: {e}\n")
            raise e

    def process_request(self, req):
        text = req.get("text")
        lang = req.get("lang", "en")
        prompt_wav = req.get("prompt_wav")
        
        if not text or not prompt_wav:
            return

        # Split sentences (simple split for streaming)
        import re
        if lang == 'zh':
            sentences = re.split(r'([。！？\n]+)', text)
            # Re-attach punctuation
            new_sentences = []
            for i in range(0, len(sentences) - 1, 2):
                new_sentences.append(sentences[i] + sentences[i+1])
            if len(sentences) % 2 == 1 and sentences[-1]:
                new_sentences.append(sentences[-1])
            sentences = new_sentences
        else:
            sentences = re.split(r'([.!?\n]+)', text)
             # Re-attach punctuation
            new_sentences = []
            for i in range(0, len(sentences) - 1, 2):
                new_sentences.append(sentences[i] + sentences[i+1])
            if len(sentences) % 2 == 1 and sentences[-1]:
                new_sentences.append(sentences[-1])
            sentences = new_sentences

        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            sentences = [text]

        print(json.dumps({"type": "start", "sample_rate": 24000}))
        sys.stdout.flush()

        for sent in sentences:
            # Generate to temp file (XTTS API limitation)
            # Ideally we would use lower level API for memory-only, but tts_to_file is stable
            temp_file = f"temp_tts_{time.time()}.wav"
            try:
                self.tts.tts_to_file(
                    text=sent,
                    speaker_wav=prompt_wav,
                    language=lang,
                    file_path=temp_file,
                    temperature=self.temperature,
                    length_penalty=self.length_penalty,
                    repetition_penalty=self.repetition_penalty,
                    top_k=self.top_k,
                    top_p=self.top_p
                )
                
                # Read and encode
                with open(temp_file, "rb") as f:
                    # Skip WAV header (44 bytes) for raw streaming if we want seamless concatenation
                    # But for simplicity, let's send full wav and let frontend handle, 
                    # OR better: read as float32 using soundfile and encode raw PCM
                    pass
                
                # Using soundfile to get raw PCM float32 or int16
                data, sr = sf.read(temp_file, dtype='int16')
                raw_bytes = data.tobytes()
                b64_data = base64.b64encode(raw_bytes).decode('utf-8')
                
                print(json.dumps({"type": "audio", "data": b64_data}))
                sys.stdout.flush()
                
            except Exception as e:
                sys.stderr.write(f"TTS Error: {e}\n")
            finally:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
        
        print(json.dumps({"type": "done"}))
        sys.stdout.flush()

def main():
    service = XTTSStreamingService()
    
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            req = json.loads(line)
            service.process_request(req)
        except json.JSONDecodeError:
            continue
        except Exception as e:
            sys.stderr.write(f"Loop Error: {e}\n")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.stderr.write(f"[TTS] Critical Error: {e}\n")
        sys.exit(1)
