import urllib.request
import time

url = 'http://127.0.0.1:9090/inference'
wav = r'e:\projects\AiforForiegnLanguageLearning\app\v5\resources\whisper\test_hello.wav'

with open(wav, 'rb') as f:
    audio = f.read()

boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
parts = []
parts.append(b'--' + boundary.encode())
parts.append(b'Content-Disposition: form-data; name="file"; filename="test.wav"')
parts.append(b'Content-Type: audio/wav')
parts.append(b'')
parts.append(audio)
parts.append(b'--' + boundary.encode())
parts.append(b'Content-Disposition: form-data; name="language"')
parts.append(b'')
parts.append(b'en')
parts.append(b'--' + boundary.encode() + b'--')

data = b'\r\n'.join(parts)
req = urllib.request.Request(url, data=data, headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
t1 = time.time()
resp = urllib.request.urlopen(req)
t2 = time.time()
body = resp.read().decode('utf-8')
print('status:', resp.status)
print('latency_ms:', int((t2-t1)*1000))
print('body:', body[:500])
