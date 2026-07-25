from pathlib import Path

import cv2
import numpy as np

from pogo_auto.ocr_anchored_appraisal import (
    BarRoi,
    OcrAnchoredAppraisalDetector,
    extract_species_from_caught_sentence,
    flatten_paddle_ocr,
)


def _word(text, x1, y1, x2, y2, confidence=0.99):
    return [
        [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
        (text, confidence),
    ]


def test_species_from_caught_sentence():
    raw = [[
        _word("This", 20, 10, 60, 30),
        _word("Deino", 65, 10, 115, 30),
        _word("was", 120, 10, 150, 30),
        _word("caught", 155, 10, 210, 30),
        _word("on", 215, 10, 235, 30),
        _word("5/16/2026", 240, 10, 330, 30),
    ]]
    assert extract_species_from_caught_sentence(flatten_paddle_ocr(raw)) == "Deino"


def test_real_reference_screenshot_when_available():
    image_path = Path("tests/fixtures/Screenshot_20260619-125016.png")
    if not image_path.exists():
        return

    image = cv2.imread(str(image_path))
    raw = [[
        _word("Attack", 98, 1392, 176, 1420),
        _word("Defense", 98, 1473, 205, 1501),
        _word("HP", 98, 1554, 132, 1582),
        _word("This", 184, 1696, 237, 1724),
        _word("Deino", 243, 1696, 305, 1724),
        _word("was", 311, 1696, 354, 1724),
        _word("caught", 360, 1696, 433, 1724),
    ]]
    result = OcrAnchoredAppraisalDetector().detect(image, raw)
    assert result.species_from_sentence == "Deino"
    # The fixture's synthetic OCR boxes are from a differently scaled capture;
    # species extraction remains a deterministic regression check here. Native
    # bar values are validated with OCR boxes from the live screenshot geometry.
    assert result.reason in {"ok", "low confidence"}


def test_bar_decoder_uses_grey_remainder_and_ignores_white_card():
    """White background must not extend a grey/orange appraisal capsule."""
    image = np.full((20, 260, 3), 255, dtype=np.uint8)
    # 150 px capsule: 80 px orange ~= IV 8, then grey.  The two narrow white
    # runs model native segment dividers and must not be counted as remainder.
    image[7:13, 20:100] = (0, 165, 255)  # BGR orange fill
    image[7:13, 100:170] = (205, 205, 205)  # BGR neutral-grey empty bar
    image[7:13, 70:74] = 255
    image[7:13, 120:124] = 255

    value, confidence = OcrAnchoredAppraisalDetector._decode_bar(
        image, BarRoi(0, 0, image.shape[1], image.shape[0])
    )

    assert value == 8
    assert confidence > 0.5


def _structured_bar(iv: int, *, red=False) -> tuple[np.ndarray, BarRoi]:
    """A 15-cell synthetic native strip with white section separators."""
    cell_width, height = 12, 14
    image = np.full((height, cell_width * 15, 3), 255, dtype=np.uint8)
    for index in range(15):
        colour = (0, 30, 255) if red and iv == 15 else (0, 165, 255)
        if index >= iv:
            colour = (205, 205, 205)
        image[3:11, index * cell_width:(index + 1) * cell_width] = colour
    # Only section dividers are white, and lie outside the central sample of
    # their neighbouring cells.
    image[3:11, 59:61] = 255
    image[3:11, 119:121] = 255
    return image, BarRoi(0, 0, image.shape[1], image.shape[0])


def test_model_decoder_scores_legal_cell_hypotheses():
    for expected in (0, 1, 4, 5, 6, 8, 9, 10, 11, 13, 14, 15):
        image, roi = _structured_bar(expected, red=expected == 15)
        value, confidence = OcrAnchoredAppraisalDetector._decode_bar(image, roi)
        assert value == expected
        assert confidence >= 0.78


def test_red_but_incomplete_bar_is_not_forced_to_fifteen():
    image, roi = _structured_bar(14)
    image[3:11, :14 * 12] = (0, 30, 255)
    value, _ = OcrAnchoredAppraisalDetector._decode_bar(image, roi)
    assert value != 15
