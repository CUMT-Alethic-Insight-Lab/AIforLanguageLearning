import os
import math
import numpy as np
import soundfile as sf


def main():
	sr = 16000
	secs = 2.0
	freq = 220.0
	n = int(sr * secs)
	t = np.arange(n, dtype=np.float32) / sr
	wave = 0.2 * np.sin(2 * math.pi * freq * t)

	# Save next to this script, cross-platform
	out = os.path.join(os.path.dirname(__file__), 'zero_shot_prompt.wav')
	sf.write(out, wave, sr)
	print('wrote', out)


if __name__ == '__main__':
	main()
