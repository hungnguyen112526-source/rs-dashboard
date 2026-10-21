"""Tải templeNightRenderer.js nguyên bản từ ThreeUI và kiểm tra SHA-256. Chạy: python get_temple_renderer.py"""
import hashlib, json, sys, urllib.request
from pathlib import Path
URL = "https://threeui.com/source-code/temple-night.json"
SHA = "9da1d88d83877141f61476d97055abe89aa3c4c008e9c098af5a4b552bed15b2"
OUT = Path(__file__).parent / "static" / "templeNightRenderer.js"

def strings(o):
    if isinstance(o, str): yield o
    elif isinstance(o, dict):
        for v in o.values(): yield from strings(v)
    elif isinstance(o, list):
        for v in o: yield from strings(v)

data = json.load(urllib.request.urlopen(URL, timeout=30))
for s in strings(data):
    if hashlib.sha256(s.encode()).hexdigest() == SHA:
        OUT.write_text(s, encoding="utf-8", newline=""); print("OK ->", OUT); break
else:
    sys.exit("Không tìm thấy file khớp SHA-256 trong bundle — dừng, không tạo file.")
