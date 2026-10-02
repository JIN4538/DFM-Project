"""Rasterize a read-only Word PDF export with bundled pypdfium2."""
import argparse
import json
from pathlib import Path

import pypdfium2 as pdfium

parser = argparse.ArgumentParser()
parser.add_argument("input_pdf", type=Path)
parser.add_argument("output_dir", type=Path)
parser.add_argument("--dpi", type=int, default=144)
args = parser.parse_args()
args.output_dir.mkdir(parents=True, exist_ok=True)
pdf = pdfium.PdfDocument(str(args.input_pdf))
summary = {"pdf": str(args.input_pdf.resolve()), "page_count": len(pdf), "dpi": args.dpi, "pages": []}
for index in range(len(pdf)):
    page = pdf[index]
    bitmap = page.render(scale=args.dpi / 72)
    image = bitmap.to_pil()
    output = args.output_dir / f"page-{index + 1}.png"
    image.save(output)
    summary["pages"].append({"path": str(output.resolve()), "width": image.width, "height": image.height})
    bitmap.close()
    page.close()
pdf.close()
(args.output_dir / "render-summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(summary, indent=2, ensure_ascii=False))
