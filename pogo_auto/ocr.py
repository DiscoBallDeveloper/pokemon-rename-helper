from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# PaddleOCR is sensitive to MKLDNN in this environment.
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_mkldnn", "0")


@dataclass(frozen=True)
class OcrText:
    text: str
    score: float


class PaddleOcrEngine:
    def __init__(self) -> None:
        from paddleocr import PaddleOCR
        self._ocr = PaddleOCR(use_angle_cls=True, lang="en")

    def predict_texts(self, image_path: str | Path) -> list[OcrText]:
        result = self._ocr.predict(str(image_path))
        if not result:
            return []

        first: Any = result[0]
        texts = first.get("rec_texts", []) if isinstance(first, dict) else []
        scores = first.get("rec_scores", []) if isinstance(first, dict) else []

        out: list[OcrText] = []
        for text, score in zip(texts, scores):
            out.append(OcrText(str(text), float(score)))
        return out
