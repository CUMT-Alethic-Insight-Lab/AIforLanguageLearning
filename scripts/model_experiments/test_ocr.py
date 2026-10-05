#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试 PaddleOCR（最小验证）"""

import os
import sys
from pathlib import Path

try:
    from PIL import Image
    import json
    from paddleocr import PaddleOCR
    
    print("✓ PaddleOCR modules imported successfully")
    
    # 测试图片路径
    image_path = Path(__file__).parent / "OCRtest.png"
    output_dir = Path(__file__).parent.parent / "backend" / "temp"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Loading image: {image_path}")
    image = Image.open(image_path)
    
    print("Initializing PaddleOCR...")
    ocr = PaddleOCR(use_textline_orientation=True, lang="japan", device="cpu")

    print("Running OCR...")
    results = ocr.predict(image)
    
    print(f"\n{'='*60}")
    print("OCR Results:")
    print(f"{'='*60}")
    
    # 保存结果
    output_file = output_dir / "ocr_result.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n✓ Results saved to: {output_file}")
    print(f"\n✓ OCR test completed successfully!")
    
except Exception as e:
    print(f"✗ Error: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)
