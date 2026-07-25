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


def find_text_center(image_path: str | Path, expected_text: str) -> tuple[int, int] | None:
    """Return the centre of an exact OCR text match in a screenshot.

    This is used for menu actions such as Pokémon GO's ``Appraise`` entry,
    where text recognition is more portable than a device-specific template.
    """
    from paddleocr import PaddleOCR

    ocr = PaddleOCR(
        lang="en",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=True,
        enable_mkldnn=False,
    )
    wanted = expected_text.casefold()
    if not hasattr(ocr, "predict"):
        # PaddleOCR 2.x returns nested [box, (text, confidence)] rows.
        def visit(node: Any) -> tuple[int, int] | None:
            if (
                isinstance(node, (list, tuple)) and len(node) == 2
                and isinstance(node[0], (list, tuple)) and len(node[0]) >= 4
                and isinstance(node[1], (list, tuple)) and len(node[1]) >= 2
                and isinstance(node[1][0], str)
            ):
                text, score = node[1][0], node[1][1]
                if text.strip().casefold() != wanted or float(score) < 0.55:
                    return None
                try:
                    xs = [float(point[0]) for point in node[0]]
                    ys = [float(point[1]) for point in node[0]]
                except (TypeError, ValueError, IndexError):
                    return None
                return round((min(xs) + max(xs)) / 2), round((min(ys) + max(ys)) / 2)
            if isinstance(node, (list, tuple)):
                for item in node:
                    match = visit(item)
                    if match is not None:
                        return match
            return None

        return visit(ocr.ocr(str(image_path), cls=True))

    result = ocr.predict(str(image_path))
    for page in result or []:
        try:
            data = dict(page)
        except (TypeError, ValueError):
            data = page
        if not hasattr(data, "get"):
            continue
        texts = data.get("rec_texts", []) or []
        scores = data.get("rec_scores", []) or []
        boxes = data.get("rec_polys") or data.get("dt_polys") or data.get("det_polys") or []
        for text, score, box in zip(texts, scores, boxes):
            if str(text).strip().casefold() != wanted or float(score) < 0.55:
                continue
            try:
                xs = [float(point[0]) for point in box]
                ys = [float(point[1]) for point in box]
            except (TypeError, ValueError, IndexError):
                continue
            return round((min(xs) + max(xs)) / 2), round((min(ys) + max(ys)) / 2)
    return None
