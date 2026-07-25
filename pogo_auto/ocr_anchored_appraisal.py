from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from statistics import median
from typing import Any, Mapping, Sequence

import cv2
import numpy as np


@dataclass(frozen=True)
class OcrWord:
    text: str
    confidence: float
    points: tuple[tuple[float, float], ...]

    @property
    def x1(self) -> float: return min(point[0] for point in self.points)
    @property
    def x2(self) -> float: return max(point[0] for point in self.points)
    @property
    def y1(self) -> float: return min(point[1] for point in self.points)
    @property
    def y2(self) -> float: return max(point[1] for point in self.points)
    @property
    def width(self) -> float: return self.x2 - self.x1
    @property
    def center_y(self) -> float: return (self.y1 + self.y2) / 2.0


@dataclass(frozen=True)
class BarRoi:
    x1: int
    y1: int
    x2: int
    y2: int


@dataclass(frozen=True)
class AppraisalDecoderConfig:
    """Conservative constants for the structured 15-cell signal decoder."""
    bar_offset_ratio: float = 0.50
    bar_height_ratio: float = 0.36
    cell_inset_ratio: float = 0.25
    min_label_confidence: float = 0.55
    min_geometry_confidence: float = 0.78
    min_winner_margin: float = 0.055
    min_bar_confidence: float = 0.65
    separator_window_ratio: float = 0.075
    red_full_threshold: float = 0.55
    label_left_tolerance_ratio: float = 0.45
    capsule_material_threshold: float = 0.14
    maximum_separator_gap_ratio: float = 0.020
    max_separator_width_disagreement: float = 0.12


@dataclass(frozen=True)
class AppraisalGeometry:
    left: int
    right: int
    width: int
    bar_height: int
    row_spacing: float
    label_to_bar_offset: float
    separator_5: int
    separator_10: int
    geometry_confidence: float
    failure_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class BarCellEvidence:
    index: int
    x1: int
    x2: int
    fill_probability: float
    grey_probability: float
    red_probability: float
    signal_quality: float


@dataclass(frozen=True)
class BarHypothesis:
    iv: int
    score: float
    fill_before_score: float
    grey_after_score: float
    separator_score: float
    endpoint_score: float
    red_consistency_score: float


@dataclass(frozen=True)
class BarDecodeResult:
    value: int | None
    confidence: float
    best_score: float
    second_best_value: int | None
    second_best_score: float
    score_margin: float
    cells: tuple[BarCellEvidence, ...]
    hypotheses: tuple[BarHypothesis, ...]
    failure_reasons: tuple[str, ...] = ()
    legacy_width_value: int | None = None


@dataclass(frozen=True)
class AnchoredIvResult:
    attack: int | None
    defense: int | None
    hp: int | None
    confidence: float
    species_from_sentence: str | None
    rois: Mapping[str, BarRoi]
    reason: str
    geometry: AppraisalGeometry | None = None
    bars: Mapping[str, BarDecodeResult] = field(default_factory=dict)


LABEL_ALIASES = {"attack": {"attack", "atk"}, "defense": {"defense", "defence", "def"}, "hp": {"hp"}}
CAUGHT_SENTENCE_RE = re.compile(r"\bthis\s+(.+?)\s+was\s+caught\b", re.IGNORECASE)


def flatten_paddle_ocr(raw: Any) -> list[OcrWord]:
    words: list[OcrWord] = []
    def visit(node: Any) -> None:
        if isinstance(node, Mapping):
            text = node.get("text")
            points = node.get("box") or node.get("bbox") or node.get("points")
            if isinstance(text, str) and points is not None:
                try:
                    words.append(OcrWord(text.strip(), float(node.get("score", node.get("confidence", 0.0))), tuple((float(p[0]), float(p[1])) for p in points)))
                except (TypeError, ValueError, IndexError):
                    pass
            return
        if isinstance(node, (list, tuple)) and len(node) == 2 and isinstance(node[1], (list, tuple)) and len(node[1]) >= 2 and isinstance(node[1][0], str):
            try:
                words.append(OcrWord(node[1][0].strip(), float(node[1][1]), tuple((float(p[0]), float(p[1])) for p in node[0])))
                return
            except (TypeError, ValueError, IndexError):
                pass
        if isinstance(node, (list, tuple)):
            for child in node: visit(child)
    visit(raw)
    return words


def extract_species_from_caught_sentence(words: Sequence[OcrWord]) -> str | None:
    if not words: return None
    ordered = sorted(words, key=lambda word: (word.center_y, word.x1))
    tolerance = max(8.0, median([max(1.0, word.y2 - word.y1) for word in ordered]) * .75)
    lines: list[list[OcrWord]] = []
    for word in ordered:
        line = next((item for item in lines if abs(median([w.center_y for w in item]) - word.center_y) <= tolerance), None)
        if line is None:
            line = []
            lines.append(line)
        line.append(word)
    texts = [" ".join(word.text for word in sorted(line, key=lambda word: word.x1)) for line in lines]
    for text in texts + [f"{texts[i]} {texts[i + 1]}" for i in range(len(texts) - 1)]:
        match = CAUGHT_SENTENCE_RE.search(text)
        if match:
            value = re.sub(r"\s+", " ", match.group(1)).strip(" .,:;-")
            if 1 <= len(value) <= 40: return value
    return None


class OcrAnchoredAppraisalDetector:
    """OCR-localized, shared-geometry decoder for the 16 legal IV states."""
    def __init__(self, **kwargs: float) -> None:
        self.config = AppraisalDecoderConfig(**kwargs)

    def detect(self, image: np.ndarray, raw_ocr: Any, *, debug_path: str | None = None) -> AnchoredIvResult:
        words = flatten_paddle_ocr(raw_ocr)
        labels = self._select_labels(words)
        species = extract_species_from_caught_sentence(words)
        if labels is None:
            return AnchoredIvResult(None, None, None, 0.0, species, {}, "missing appraisal labels")
        geometry = self._fit_geometry(image, labels)
        if geometry.width <= 0:
            if debug_path:
                self._write_geometry_failure_debug(image, labels, geometry, debug_path)
            return AnchoredIvResult(None, None, None, 0.0, species, {}, "low confidence", geometry)
        rois = {
            name: BarRoi(geometry.left, max(0, round(label.center_y + geometry.label_to_bar_offset - geometry.bar_height / 2)), geometry.right, min(image.shape[0], round(label.center_y + geometry.label_to_bar_offset + geometry.bar_height / 2)))
            for name, label in labels.items()
        }
        bars = {name: self._decode_cells(image, roi, geometry) for name, roi in rois.items()}
        values = {name: result.value for name, result in bars.items()}
        confidence = min([geometry.geometry_confidence] + [result.confidence for result in bars.values()])
        reasons = [reason for result in bars.values() for reason in result.failure_reasons]
        # Detailed blocking reasons live on each BarDecodeResult.  Preserve
        # the public coarse result reason used by the legacy CSV path.
        reason = "ok" if not reasons else "low confidence"
        if debug_path:
            self._write_debug(image, labels, geometry, rois, bars, debug_path)
        return AnchoredIvResult(values["attack"], values["defense"], values["hp"], confidence, species, rois, reason, geometry, bars)

    def _select_labels(self, words: Sequence[OcrWord]) -> dict[str, OcrWord] | None:
        candidates: dict[str, list[OcrWord]] = {name: [] for name in LABEL_ALIASES}
        for word in words:
            normalized = re.sub(r"[^a-z]", "", word.text.casefold())
            if word.confidence >= self.config.min_label_confidence:
                for name, aliases in LABEL_ALIASES.items():
                    if normalized in aliases: candidates[name].append(word)
        if any(not value for value in candidates.values()): return None
        choices = []
        for attack in candidates["attack"]:
            for defense in candidates["defense"]:
                for hp in candidates["hp"]:
                    if attack.center_y < defense.center_y < hp.center_y:
                        g1, g2 = defense.center_y - attack.center_y, hp.center_y - defense.center_y
                        spacing = median((g1, g2))
                        score = abs(g1 - g2) / max(1, spacing) + (max(attack.x1, defense.x1, hp.x1) - min(attack.x1, defense.x1, hp.x1)) / max(1, defense.width)
                        choices.append((score, {"attack": attack, "defense": defense, "hp": hp}))
        return min(choices, key=lambda item: item[0])[1] if choices else None

    def _fit_geometry(self, image: np.ndarray, labels: Mapping[str, OcrWord]) -> AppraisalGeometry:
        attack, defense, hp = labels["attack"], labels["defense"], labels["hp"]
        g1, g2 = defense.center_y - attack.center_y, hp.center_y - defense.center_y
        spacing = float(median((g1, g2)))
        prior_left = round(median([word.x1 for word in labels.values()]))
        gap_error = abs(g1 - g2) / max(1.0, spacing)
        x_error = (max(word.x1 for word in labels.values()) - min(word.x1 for word in labels.values())) / max(1.0, defense.width)
        reasons: list[str] = []
        if spacing <= 0: reasons.append("invalid shared bar geometry")
        if gap_error > .28 or x_error > .55: reasons.append("labels failed spacing/alignment validation")
        confidence = max(0.0, 1.0 - 1.8 * gap_error - .8 * x_error)
        if confidence < self.config.min_geometry_confidence: reasons.append("geometry confidence below threshold")
        bar_height = max(7, round(spacing * self.config.bar_height_ratio))
        offset = spacing * self.config.bar_offset_ratio
        # Search only around the OCR-derived panel, then combine the three
        # material profiles.  Neither screen width nor a coloured endpoint is
        # used as a capsule boundary: grey tails contribute equally.
        search_left = max(0, prior_left - round(defense.width * self.config.label_left_tolerance_ratio))
        search_width = max(round(defense.width * 4.2), round(spacing * 4.8), 90)
        search_right = min(image.shape[1], search_left + search_width)
        profiles: list[np.ndarray] = []
        row_profiles: list[np.ndarray] = []
        for label in (attack, defense, hp):
            center = round(label.center_y + offset)
            strip = image[max(0, center - bar_height):min(image.shape[0], center + bar_height + 1), search_left:search_right]
            profile = self._material_profile(strip)
            profiles.append(profile)
            row_profiles.append(profile >= self.config.capsule_material_threshold)
        if not profiles or search_right - search_left < 45:
            reasons.append("CAPSULE_RIGHT_NOT_FOUND")
            return AppraisalGeometry(prior_left, prior_left, 0, bar_height, spacing, offset, prior_left, prior_left, 0.0, tuple(reasons))
        shared = np.median(np.stack(profiles), axis=0)
        support = np.sum(np.stack(row_profiles), axis=0)
        material = (shared >= self.config.capsule_material_threshold) & (support >= 2)
        # Divider/anti-alias gaps scale with the detected UI, not with a
        # particular phone's pixels.  At 1008px wide this retains the former
        # ~10px allowance; smaller/larger displays scale proportionally.
        maximum_gap = max(2, round((search_right - search_left) * self.config.maximum_separator_gap_ratio))
        material = self._close_short_gaps(material, maximum_gap)
        components = self._components(material)
        tolerance = max(8, round(defense.width * self.config.label_left_tolerance_ratio))
        minimum_capsule_width = max(24, round(defense.width * 1.25))
        viable = [item for item in components if abs(search_left + item[0] - prior_left) <= tolerance and item[1] - item[0] >= minimum_capsule_width]
        if not viable:
            reasons.append("CAPSULE_LEFT_NOT_FOUND")
            reasons.append("CAPSULE_RIGHT_NOT_FOUND")
            return AppraisalGeometry(prior_left, prior_left, 0, bar_height, spacing, offset, prior_left, prior_left, 0.0, tuple(reasons))
        start, end = max(viable, key=lambda item: item[1] - item[0])
        left, right = search_left + start, search_left + end + 1
        width = right - left
        if width < minimum_capsule_width:
            reasons.append("CAPSULE_WIDTH_INVALID")
        local = shared[start:end + 1]
        sep5, sep10, separator_confidence, separator_reason = self._refine_separators(local, left)
        # Missing visible dividers reduce confidence, but do not prevent a
        # debug/cell pass.  Some frames antialias a divider away; the 15-cell
        # model can still reject the frame conservatively on margin/quality.
        width_estimates = [float(width)]
        if sep5 is not None: width_estimates.append(3.0 * (sep5 - left))
        if sep10 is not None: width_estimates.append(1.5 * (sep10 - left))
        refined_width = float(median(width_estimates))
        disagreement = max(abs(value - refined_width) / max(1.0, refined_width) for value in width_estimates)
        if disagreement > self.config.max_separator_width_disagreement:
            reasons.append("SEPARATOR_WIDTH_DISAGREEMENT")
        # Keep actual material edges; separator estimates validate them rather
        # than silently stretching or shrinking the observed capsule.
        edge_support = min(1.0, float(np.mean(support[start:end + 1] >= 2)) / .85)
        confidence *= edge_support * (.70 + .30 * separator_confidence)
        if confidence < self.config.min_geometry_confidence:
            reasons.append("geometry confidence below threshold")
        return AppraisalGeometry(left, right, width, bar_height, spacing, offset, sep5 or round(left + width / 3), sep10 or round(left + 2 * width / 3), confidence, tuple(sorted(set(reasons))))

    @staticmethod
    def _close_short_gaps(values: np.ndarray, maximum_gap: int) -> np.ndarray:
        result = values.astype(bool).copy()
        true = np.flatnonzero(result)
        for left, right in zip(true, true[1:]):
            if 0 < right - left - 1 <= maximum_gap:
                result[left + 1:right] = True
        return result

    @staticmethod
    def _components(values: np.ndarray) -> list[tuple[int, int]]:
        result: list[tuple[int, int]] = []
        for index in np.flatnonzero(values):
            if not result or index > result[-1][1] + 1: result.append((int(index), int(index)))
            else: result[-1] = (result[-1][0], int(index))
        return result

    @staticmethod
    def _material_profile(strip: np.ndarray) -> np.ndarray:
        if strip.size == 0: return np.zeros(0, dtype=float)
        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV).astype(np.float32)
        bgr = strip.astype(np.float32)
        hue, sat, val = hsv[..., 0], hsv[..., 1] / 255.0, hsv[..., 2] / 255.0
        spread = (bgr.max(axis=2) - bgr.min(axis=2)) / 255.0
        warm = np.maximum(np.exp(-((hue - 21.0) / 16.0) ** 2), np.exp(-((np.minimum(hue, 180 - hue)) / 12.0) ** 2)) * np.clip((sat - .18) / .55, 0, 1)
        neutral_grey = (1 - spread / .20) * np.clip((val - .48) / .22, 0, 1) * np.clip((.96 - val) / .20, 0, 1)
        # The translucent native empty capsule has a lower raw neutral score
        # than an opaque swatch, but remains distinct from card-white (zero).
        # Calibrate that membership before comparing legal cell hypotheses.
        grey = np.clip(neutral_grey * 2.5, 0, 1)
        # A bar occupies only a thin centre band of this deliberately broad
        # OCR-derived strip.  The upper percentile keeps that signal while
        # ignoring white margin above/below the strip.
        return np.quantile(np.maximum(warm, grey), .85, axis=0)

    def _refine_separators(self, profile: np.ndarray, left: int) -> tuple[int | None, int | None, float, str | None]:
        width = len(profile)
        locations: list[int | None] = []
        for fraction in (1 / 3, 2 / 3):
            expected = round(width * fraction)
            radius = max(3, round(width * self.config.separator_window_ratio))
            a, b = max(1, expected - radius), min(width - 1, expected + radius + 1)
            if b <= a: locations.append(None); continue
            local = profile[a:b]
            offset = int(np.argmin(local))
            candidate = a + offset
            # Divider is a local material interruption, not merely a low
            # profile elsewhere in the broad search strip.
            neighbours = np.concatenate((profile[max(0, candidate - 5):candidate], profile[candidate + 1:min(width, candidate + 6)]))
            locations.append(left + candidate if len(neighbours) and profile[candidate] + .04 < float(np.mean(neighbours)) else None)
        found = sum(value is not None for value in locations)
        return locations[0], locations[1], found / 2.0, (None if found == 2 else "SEPARATOR_5_NOT_FOUND" if locations[0] is None else "SEPARATOR_10_NOT_FOUND")

    def _decode_cells(self, image: np.ndarray, roi: BarRoi, geometry: AppraisalGeometry) -> BarDecodeResult:
        strip = image[roi.y1:roi.y2, roi.x1:roi.x2]
        if strip.size == 0: return self._failed("empty bar strip")
        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV).astype(np.float32)
        bgr = strip.astype(np.float32)
        hue, sat, val = hsv[..., 0], hsv[..., 1] / 255.0, hsv[..., 2] / 255.0
        spread = (bgr.max(axis=2) - bgr.min(axis=2)) / 255.0
        # Soft colour evidence, aggregated only inside the known bar geometry.
        warm_hue = np.maximum(np.exp(-((hue - 21.0) / 16.0) ** 2), np.exp(-((np.minimum(hue, 180 - hue)) / 12.0) ** 2))
        fill = np.clip(warm_hue * np.clip((sat - .18) / .55, 0, 1) * np.clip((val - .28) / .45, 0, 1), 0, 1)
        red = np.clip(np.exp(-((np.minimum(hue, 180 - hue)) / 10.0) ** 2) * np.clip((sat - .25) / .55, 0, 1), 0, 1)
        grey = np.clip(2.5 * (1 - spread / .20) * np.clip((val - .48) / .22, 0, 1) * np.clip((.96 - val) / .20, 0, 1), 0, 1)
        # Rectify vertically before sampling cells.  The OCR-derived ROI is
        # deliberately generous; choose the compact material band rather than
        # allowing white card pixels above/below the capsule into each median.
        row_support = np.maximum(fill, grey).mean(axis=1)
        peak_y = int(np.argmax(row_support))
        peak_support = float(row_support[peak_y])
        if peak_support < .04:
            return self._failed("bar material not found")
        active_rows = row_support >= peak_support * .55
        y1 = y2 = peak_y
        while y1 > 0 and active_rows[y1 - 1]: y1 -= 1
        while y2 + 1 < len(active_rows) and active_rows[y2 + 1]: y2 += 1
        cells: list[BarCellEvidence] = []
        for index in range(15):
            x1, x2 = geometry.width * index / 15, geometry.width * (index + 1) / 15
            inset = (x2 - x1) * self.config.cell_inset_ratio
            a, b = max(0, round(x1 + inset)), min(geometry.width, round(x2 - inset))
            if b <= a: return self._failed("invalid cell geometry")
            patch_fill, patch_grey, patch_red = fill[y1:y2 + 1, a:b], grey[y1:y2 + 1, a:b], red[y1:y2 + 1, a:b]
            f, g, r = float(np.median(patch_fill)), float(np.median(patch_grey)), float(np.median(patch_red))
            quality = min(1.0, max(f, g) + abs(f - g) * .25)
            cells.append(BarCellEvidence(index, roi.x1 + a, roi.x1 + b, f, g, r, quality))
        hypotheses = tuple(self._score_hypothesis(cells, iv) for iv in range(16))
        ordered = sorted(hypotheses, key=lambda item: item.score, reverse=True)
        best, second = ordered[0], ordered[1]
        margin = best.score - second.score
        endpoint = cells[-1]
        all_filled = min(cell.fill_probability for cell in cells) >= .55
        no_grey_tail = max(cell.grey_probability for cell in cells[-2:]) < .35
        red_full = float(np.median([cell.red_probability for cell in cells])) >= self.config.red_full_threshold
        reasons: list[str] = []
        if geometry.geometry_confidence < self.config.min_geometry_confidence: reasons.append("geometry confidence below threshold")
        if margin < self.config.min_winner_margin: reasons.append("hypothesis margin below threshold")
        if best.iv == 15 and not (all_filled and endpoint.fill_probability >= .65 and no_grey_tail and (red_full or endpoint.fill_probability >= .82)):
            reasons.append("ambiguous full bar")
        if best.iv < 15 and red_full: reasons.append("red/full state disagreement")
        confidence = min(geometry.geometry_confidence, min(cell.signal_quality for cell in cells), min(1.0, margin / .10))
        if confidence < self.config.min_bar_confidence: reasons.append("bar confidence below threshold")
        value = None if reasons else best.iv
        return BarDecodeResult(value, confidence, best.score, second.iv, second.score, margin, tuple(cells), hypotheses, tuple(reasons), self._legacy_width_shadow(cells))

    @staticmethod
    def _score_hypothesis(cells: Sequence[BarCellEvidence], iv: int) -> BarHypothesis:
        before, after = cells[:iv], cells[iv:]
        fill_before = float(np.mean([cell.fill_probability for cell in before])) if before else 0.0
        grey_after = float(np.mean([cell.grey_probability for cell in after])) if after else 0.0
        expected = np.array([index < iv for index in range(15)], dtype=bool)
        fill = np.array([cell.fill_probability for cell in cells])
        grey = np.array([cell.grey_probability for cell in cells])
        # Directly compare all 15 observations to this legal hypothesis.  In
        # particular IV 0 has no imaginary "filled before endpoint" region:
        # its first cell must look grey, otherwise IV 1 wins.
        fill_match = float(np.mean(np.where(expected, fill, 1.0 - fill)))
        grey_match = float(np.mean(np.where(expected, 1.0 - grey, grey)))
        if iv == 0:
            endpoint = cells[0].grey_probability
        elif iv == 15:
            endpoint = cells[-1].fill_probability
        else:
            endpoint = (cells[iv - 1].fill_probability + cells[iv].grey_probability) / 2.0
        separator = float(np.mean([abs(cells[index].fill_probability - cells[index + 1].fill_probability) for index in (4, 9)]))
        # Separators are support only: legal IV values may cross them, so they
        # must not decide a value by themselves.
        separator_score = 1.0 - min(1.0, separator) * .15
        red_score = float(np.mean([cell.red_probability for cell in cells[:iv]])) if iv else 1.0
        red_consistency = red_score if iv == 15 else 1.0 - max(0.0, red_score - .45)
        # ``fill_match`` gives unexpected fill after the endpoint the same
        # strong penalty as missing fill before it; grey is corroborating
        # evidence because the empty native bar is less saturated/less stable.
        score = .74 * fill_match + .14 * grey_match + .08 * endpoint + .02 * separator_score + .02 * red_consistency
        return BarHypothesis(iv, float(score), fill_before, grey_after, separator_score, endpoint, red_consistency)

    @staticmethod
    def _legacy_width_shadow(cells: Sequence[BarCellEvidence]) -> int:
        """Diagnostic-only continuous estimate; never used to accept a scan."""
        return int(np.clip(round(sum(cell.fill_probability for cell in cells)), 0, 15))

    @staticmethod
    def _failed(reason: str) -> BarDecodeResult:
        return BarDecodeResult(None, 0.0, 0.0, None, 0.0, 0.0, (), (), (reason,))

    @staticmethod
    def _decode_bar(image: np.ndarray, roi: BarRoi) -> tuple[int | None, float]:
        """Compatibility helper for callers; uses the model decoder, not width."""
        crop = image[roi.y1:roi.y2, roi.x1:roi.x2]
        if crop.size == 0:
            return None, 0.0
        # Compatibility callers do not have OCR shared geometry.  Trim only
        # obvious card-white margins; this finds capsule bounds but never
        # determines an IV from a measured width.
        spread = crop.max(axis=2).astype(int) - crop.min(axis=2).astype(int)
        material = (spread > 12) | (crop.max(axis=2) < 245)
        columns = np.flatnonzero(material.mean(axis=0) >= 0.12)
        if len(columns):
            roi = BarRoi(roi.x1 + int(columns[0]), roi.y1, roi.x1 + int(columns[-1]) + 1, roi.y2)
        width = roi.x2 - roi.x1
        geometry = AppraisalGeometry(roi.x1, roi.x2, width, roi.y2 - roi.y1, 1, 0, roi.x1 + round(width / 3), roi.x1 + round(2 * width / 3), 1.0)
        result = OcrAnchoredAppraisalDetector()._decode_cells(image, roi, geometry)
        return result.value, result.confidence

    def _write_debug(self, image: np.ndarray, labels: Mapping[str, OcrWord], geometry: AppraisalGeometry, rois: Mapping[str, BarRoi], bars: Mapping[str, BarDecodeResult], debug_path: str) -> None:
        debug = image.copy()
        for name, roi in rois.items():
            cv2.rectangle(debug, (geometry.left, roi.y1), (geometry.right, roi.y2), (0, 255, 0), 2)
            # Blue lines are the 15 equal theoretical cells.  They are not
            # the smaller inset sampling patches used for colour evidence.
            for index in range(16):
                x = round(geometry.left + geometry.width * index / 15)
                cv2.line(debug, (x, roi.y1), (x, roi.y2), (255, 180, 0), 1)
            for cell in bars[name].cells:
                # Yellow rectangle: central 50% of that cell actually
                # sampled.  It deliberately avoids rounded ends/dividers.
                cv2.rectangle(debug, (cell.x1, roi.y1 + 3), (cell.x2, roi.y2 - 3), (0, 255, 255), 1)
                cv2.putText(debug, f"{cell.fill_probability:.1f}", (cell.x1, roi.y2 + 14), cv2.FONT_HERSHEY_SIMPLEX, .28, (0, 255, 255), 1)
            result = bars[name]
            cv2.putText(debug, f"{name}={result.value if result.value is not None else '?'} runner={result.second_best_value} m={result.score_margin:.2f}", (roi.x1, max(20, roi.y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, .45, (0, 255, 0), 1)
        if not cv2.imwrite(debug_path, debug): raise IOError(f"Could not write debug image: {debug_path}")
        sidecar = Path(debug_path).with_suffix(".json")
        sidecar.write_text(json.dumps({"geometry": geometry.__dict__, "bars": {name: {"value": bar.value, "confidence": bar.confidence, "score_margin": bar.score_margin, "legacy_width_value": bar.legacy_width_value, "cells": [cell.__dict__ for cell in bar.cells], "hypotheses": [item.__dict__ for item in bar.hypotheses], "failure_reasons": bar.failure_reasons} for name, bar in bars.items()}}, indent=2), encoding="utf-8")

    @staticmethod
    def _write_geometry_failure_debug(image: np.ndarray, labels: Mapping[str, OcrWord], geometry: AppraisalGeometry, debug_path: str) -> None:
        debug = image.copy()
        for name, label in labels.items():
            cv2.rectangle(debug, (round(label.x1), round(label.y1)), (round(label.x2), round(label.y2)), (255, 0, 0), 2)
            cv2.putText(debug, name, (round(label.x1), round(label.y1) - 5), cv2.FONT_HERSHEY_SIMPLEX, .45, (255, 0, 0), 1)
        cv2.putText(debug, "geometry fit failed", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 0, 255), 2)
        cv2.imwrite(debug_path, debug)
        Path(debug_path).with_suffix(".json").write_text(json.dumps({"geometry": geometry.__dict__, "bars": {}}, indent=2), encoding="utf-8")
