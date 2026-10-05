# End-to-End Latency & Accuracy Test Report

**Date**: 2025-11-21
**Environment**: RTX 5080 (sm_120), CUDA 13.0, PyTorch 2.10 Nightly
**Models**:
- **TTS**: XTTS v2 (Streaming Mode - Sentence Level)
- **ASR**: Faster Whisper `large-v3` (Float16)

## Test Methodology
1. **Warmup**: Run both models once to clear JIT/Initialization overhead.
2. **Flow**:
   - Input Text -> XTTS -> Audio (First Sentence)
   - Audio -> Whisper -> Recognized Text
3. **Metrics**:
   - **XTTS Latency**: Time from input to generation of first sentence audio.
   - **ASR Latency**: Time to transcribe the generated audio.
   - **Total E2E**: Total time from text input to recognized text available.
   - **Accuracy**: Character Error Rate (CER) / Match Rate.

## Results

| Language | XTTS Latency (s) | ASR Latency (s) | Total E2E (s) | Accuracy | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Warmup** | 1.06 | 13.44 | 14.50 | 96.00% | High ASR latency due to first-run init |
| **Chinese (ZH)** | 1.17 | 1.57 | 2.74 | 93.33% | Punctuation diff (，vs ,) |
| **English (EN)** | 1.35 | 1.21 | 2.55 | 100.00% | Perfect match |
| **Japanese (JA)** | 1.02 | 1.47 | 2.49 | 100.00% | Perfect match |

## Analysis
- **Performance**: The RTX 5080 handles `large-v3` ASR extremely fast (~1.2-1.5s for a sentence).
- **Latency**:
  - **Time to Hear (First Sentence)**: ~1.0 - 1.3 seconds.
  - **Turn-around Time**: ~2.5 seconds.
- **Quality**: Accuracy is near perfect across all three languages.

## Recommendations
- **Latency Optimization**:
  - Current XTTS implementation waits for the full sentence to be generated before saving. True chunk-level streaming (playing audio bytes as they arrive) could reduce "Time to Hear" to < 500ms.
  - ASR is already very fast. Using `medium` model might save ~200ms but `large-v3` is preferred for accuracy.
