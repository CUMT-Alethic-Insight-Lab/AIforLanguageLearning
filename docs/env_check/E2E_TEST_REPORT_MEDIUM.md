# End-to-End Latency & Accuracy Test Report (Medium Model)

**Date**: 2025-11-21
**Environment**: RTX 5080 (sm_120), CUDA 13.0, PyTorch 2.10 Nightly
**Models**:
- **TTS**: XTTS v2 (Streaming Mode - Sentence Level)
- **ASR**: Faster Whisper `medium` (Float16)

## Results

| Language | XTTS Latency (s) | ASR Latency (s) | Total E2E (s) | Accuracy | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Warmup** | 0.94 | 0.84 | 1.77 | 88.00% | "Warm up, test" vs "Warmup test." |
| **Chinese (ZH)** | 1.02 | 1.01 | 2.03 | 89.66% | Missed punctuation, space inserted |
| **English (EN)** | 0.97 | 0.81 | 1.78 | 100.00% | Perfect match |
| **Japanese (JA)** | 1.08 | 0.91 | 1.99 | 89.47% | "エンドツーエンド" -> "エンド2エンド" |

## Comparison: Large-v3 vs Medium

| Metric | Large-v3 | Medium | Improvement |
| :--- | :--- | :--- | :--- |
| **Avg ASR Latency** | ~1.42s | ~0.91s | **~36% Faster** |
| **Avg Total E2E** | ~2.59s | ~1.93s | **~0.66s Faster** |
| **Accuracy (ZH)** | 93.33% | 89.66% | Slight drop (punctuation) |
| **Accuracy (JA)** | 100.00% | 89.47% | Drop (Katakana/Number normalization) |

## Conclusion
Switching to the `medium` model significantly reduces ASR latency (sub-1 second) and brings the total E2E turnaround time to under 2 seconds. While there is a minor drop in normalization accuracy (e.g., "two" becoming "2"), the semantic content remains accurate. For real-time dialogue, `medium` offers a better trade-off.
