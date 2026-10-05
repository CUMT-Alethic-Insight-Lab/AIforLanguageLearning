import os
import sys
import json
from pathlib import Path

try:
    import requests  # type: ignore
except Exception as e:
    print("[whisper_http_probe] Missing dependency: requests. Please install it in your Python env.")
    print("Hint: conda run -p <env> python -m pip install requests")
    sys.exit(2)

SERVER = os.getenv("WHISPER_SERVER_URL", "http://127.0.0.1:8080")
AUDIO = os.getenv("WHISPER_AUDIO", str(Path(__file__).with_name("zero_shot_prompt.wav")))

def try_post(url: str, files_key: str):
    with open(AUDIO, "rb") as f:
        files = {files_key: (Path(AUDIO).name, f, "audio/wav")}
        data = {"temperature": "0.0"}
        r = requests.post(url, files=files, data=data, timeout=60)
        return r

def main():
    if not Path(AUDIO).exists():
        print(f"[whisper_http_probe] Audio file not found: {AUDIO}")
        sys.exit(1)
    tried = []
    endpoints = [
        (f"{SERVER.rstrip('/')}/inference", "audio"),
        (f"{SERVER.rstrip('/')}/inference", "file"),
        (f"{SERVER.rstrip('/')}/transcribe", "audio"),
        (f"{SERVER.rstrip('/')}/transcribe", "file"),
    ]
    for url, key in endpoints:
        try:
            res = try_post(url, key)
            tried.append((url, key, res.status_code))
            if res.ok:
                print(f"[whisper_http_probe] OK {url} ({key})")
                txt = None
                try:
                    js = res.json()
                    txt = js.get("text") or js.get("result") or js.get("transcription") or js
                except Exception:
                    txt = res.text[:200]
                print(f"[whisper_http_probe] Response: {txt}")
                return 0
            else:
                print(f"[whisper_http_probe] {url} ({key}) -> HTTP {res.status_code}")
        except requests.exceptions.ConnectionError:
            print(f"[whisper_http_probe] Cannot connect to server at {SERVER}. Is whisper.cpp server running?")
            break
        except Exception as e:
            print(f"[whisper_http_probe] Error posting to {url} ({key}): {e}")
    print("[whisper_http_probe] Failed to probe known endpoints.")
    print("Try starting whisper.cpp server and set WHISPER_SERVER_URL, e.g. http://127.0.0.1:8080")
    return 1

if __name__ == "__main__":
    sys.exit(main())
