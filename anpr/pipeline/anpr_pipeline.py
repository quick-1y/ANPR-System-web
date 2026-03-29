# /anpr/pipeline/anpr_pipeline.py
"""Пайплайн объединяющий детекцию и OCR."""

from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol

import numpy as np

from anpr.postprocessing.validator import PlatePostProcessor
from anpr.preprocessing.plate_preprocessor import PlatePreprocessor
from common.logging import get_logger

if TYPE_CHECKING:
    from anpr.recognition.crnn_recognizer import CRNNRecognizer

logger = get_logger(__name__)


class BatchRecognizer(Protocol):
    """Минимальный контракт OCR-распознавателя для упрощения тестирования."""

    def recognize_batch(self, plate_images: List[np.ndarray]) -> List[tuple[str, float]]:
        ...


_CONSECUTIVE_FAILURE_LIMIT = 5


@dataclass
class _TrackOCRState:
    """Per-track OCR processing state for budget management."""

    ocr_attempts: int = 0
    finalized: bool = False
    result_emitted: bool = False
    unreadable_emitted: bool = False
    last_update: float = 0.0
    consecutive_failures: int = 0


class TrackAggregator:
    """Агрегирует результаты распознавания в рамках одного трека.

    Each track has a limited OCR budget (``max_ocr_attempts``).  Once
    consensus is reached **or** the budget is exhausted, the track is
    *finalized* and no further OCR work is performed for it.

    Finalization outcomes:
    - **Consensus** — a plate that achieved quorum + weighted majority.
    - **Best candidate** — strongest candidate when budget runs out without
      full quorum.
    - **Unreadable** — no valid candidate exists; the caller can emit a
      single "unreadable" event via :meth:`should_emit_unreadable`.
    """

    _EVICT_INTERVAL = 10.0  # seconds between stale-track sweeps

    def __init__(
        self,
        best_shots: int,
        ttl_seconds: float = 30.0,
        max_ocr_attempts: int = 15,
        channel_label: str = "",
        max_consecutive_empty_ocr: int = _CONSECUTIVE_FAILURE_LIMIT,
    ):
        self.best_shots = max(1, best_shots)
        self.ttl_seconds = max(5.0, float(ttl_seconds))
        self.max_ocr_attempts = max(1, max_ocr_attempts)
        self.max_consecutive_empty_ocr = max(0, max_consecutive_empty_ocr)
        self.track_texts: Dict[int, deque[tuple[str, float]]] = {}
        self.last_emitted: Dict[int, str] = {}
        self._track_ts: Dict[int, float] = {}
        self._track_states: Dict[int, _TrackOCRState] = {}
        self._last_evict: float = 0.0
        self._channel_label = channel_label
        # Set by add_result for the caller to inspect:
        # "consensus" | "budget_best" | "budget_none" | ""
        self.last_result_type: str = ""

    # ---- lifecycle helpers ----

    def _evict_stale(self, now: float) -> None:
        stale = [tid for tid, ts in self._track_ts.items() if now - ts > self.ttl_seconds]
        for tid in stale:
            self.track_texts.pop(tid, None)
            self.last_emitted.pop(tid, None)
            self._track_ts.pop(tid, None)
            self._track_states.pop(tid, None)

    def should_process(self, track_id: int) -> bool:
        """Return *True* if OCR should still run for *track_id*."""
        state = self._track_states.get(track_id)
        if state is None:
            return True
        if state.finalized:
            # Keep the timestamp alive so the track is not evicted while the
            # detector still reports it.
            self._track_ts[track_id] = time.monotonic()
            return False
        return True

    def should_emit_unreadable(self, track_id: int) -> bool:
        """Return *True* exactly once for tracks finalized without a valid result."""
        state = self._track_states.get(track_id)
        if state is None:
            return False
        if not state.finalized or state.result_emitted or state.unreadable_emitted:
            return False
        state.unreadable_emitted = True
        return True

    # ---- candidate selection ----

    def _best_candidate(self, track_id: int) -> str:
        """Pick the strongest candidate from the bucket (no quorum required)."""
        bucket = self.track_texts.get(track_id)
        if not bucket:
            return ""
        weights: Dict[str, float] = {}
        counts: Counter[str] = Counter()
        for text, confidence in bucket:
            weights[text] = weights.get(text, 0.0) + confidence
            counts[text] += 1
        if not weights:
            return ""
        return max(weights, key=lambda v: (weights[v], counts[v]))

    # ---- main API ----

    def get_track_attempts(self, track_id: int) -> int:
        """Возвращает текущее количество OCR-попыток для трека."""
        state = self._track_states.get(track_id)
        return state.ocr_attempts if state else 0

    def add_result(self, track_id: int, text: str, confidence: float) -> str:
        """Record an OCR result for *track_id* and return the consensus plate
        (or ``""`` if no result should be emitted yet).

        *text* may be empty for low-confidence detections — the attempt is
        still counted toward the OCR budget.
        """
        now = time.monotonic()
        self._track_ts[track_id] = now
        if now - self._last_evict > self._EVICT_INTERVAL:
            self._evict_stale(now)
            self._last_evict = now

        state = self._track_states.setdefault(track_id, _TrackOCRState())
        if state.finalized:
            self.last_result_type = ""
            return ""

        state.ocr_attempts += 1
        state.last_update = now
        self.last_result_type = ""

        # Only add non-empty text to the candidate pool.
        if text:
            state.consecutive_failures = 0
            bucket = self.track_texts.setdefault(track_id, deque(maxlen=self.best_shots))
            bucket.append((text, max(0.0, float(confidence))))

            weights: Dict[str, float] = {}
            counts: Counter[str] = Counter()
            total_weight = 0.0
            for entry_text, entry_confidence in bucket:
                weights[entry_text] = weights.get(entry_text, 0.0) + entry_confidence
                counts[entry_text] += 1
                total_weight += entry_confidence

            if weights and total_weight > 0:
                consensus = max(weights, key=lambda value: (weights[value], counts[value]))
                consensus_weight = weights[consensus]
                quorum = max(1, (self.best_shots + 1) // 2)
                has_quorum = len(bucket) >= self.best_shots and counts[consensus] >= quorum
                has_weighted_majority = consensus_weight >= total_weight * 0.5
                if has_quorum and has_weighted_majority and self.last_emitted.get(track_id) != consensus:
                    self.last_emitted[track_id] = consensus
                    state.result_emitted = True
                    state.finalized = True
                    self.last_result_type = "consensus"
                    logger.info(
                        "%s, трек %d: номер \"%s\" подтверждён по консенсусу после %d OCR попыток.",
                        self._channel_label,
                        track_id,
                        consensus,
                        state.ocr_attempts,
                    )
                    return consensus
        else:
            state.consecutive_failures += 1
            # Early exit: if N consecutive attempts produced nothing,
            # the plate is likely unreadable — stop wasting CPU.
            if self.max_consecutive_empty_ocr > 0 and state.consecutive_failures >= self.max_consecutive_empty_ocr:
                state.finalized = True
                self.last_result_type = "budget_none"
                logger.info(
                    "%s, трек %d: трек завершён досрочно — текст не распознан %d раз подряд "
                    "(порог %d). Всего OCR попыток: %d. Номер не найден.",
                    self._channel_label,
                    track_id,
                    state.consecutive_failures,
                    self.max_consecutive_empty_ocr,
                    state.ocr_attempts,
                )
                return ""

        # Budget exhaustion — try to salvage the best candidate.
        if state.ocr_attempts >= self.max_ocr_attempts:
            best = self._best_candidate(track_id)
            if best and not state.result_emitted:
                self.last_emitted[track_id] = best
                state.result_emitted = True
                state.finalized = True
                self.last_result_type = "budget_best"
                # INFO log deferred to process_frame where validation
                # result is known (combined message).
                return best
            state.finalized = True
            self.last_result_type = "budget_none"
            logger.info(
                "%s, трек %d: лимит OCR попыток исчерпан (%d), кандидатов не найдено.",
                self._channel_label,
                track_id,
                state.ocr_attempts,
            )

        return ""

    def reset(self, track_id: int) -> None:
        """Сбрасывает историю кандидатов, сохраняя счётчик OCR-попыток."""
        self.track_texts.pop(track_id, None)
        self.last_emitted.pop(track_id, None)
        state = self._track_states.get(track_id)
        if state:
            state.result_emitted = False
            # Only allow more OCR attempts if budget remains.
            if state.ocr_attempts < self.max_ocr_attempts:
                state.finalized = False


class TrackDirectionEstimator:
    """Оценивает направление движения по истории рамок номера."""

    APPROACHING = "APPROACHING"
    RECEDING = "RECEDING"
    UNKNOWN = "UNKNOWN"

    _EVICT_INTERVAL = 10.0  # seconds between stale-track sweeps

    def __init__(
        self,
        history_size: int = 12,
        min_track_length: int = 3,
        smoothing_window: int = 5,
        confidence_threshold: float = 0.55,
        jitter_pixels: float = 1.0,
        min_area_change_ratio: float = 0.02,
        history_ttl_seconds: float = 30.0,
    ) -> None:
        self.history_size = max(1, history_size)
        self.min_track_length = max(1, min_track_length)
        self.smoothing_window = max(1, smoothing_window)
        self.confidence_threshold = max(0.0, min(1.0, confidence_threshold))
        self.jitter_pixels = max(0.0, jitter_pixels)
        self.min_area_change_ratio = max(0.0, min_area_change_ratio)
        self.history_ttl_seconds = max(5.0, float(history_ttl_seconds))
        self._history: Dict[int, deque[tuple[float, float]]] = {}
        self._history_ts: Dict[int, float] = {}
        self._last_evict: float = 0.0

    @classmethod
    def from_config(cls, config: Dict[str, float | int]) -> "TrackDirectionEstimator":
        return cls(
            history_size=int(config.get("history_size", 12)),
            min_track_length=int(config.get("min_track_length", 3)),
            smoothing_window=int(config.get("smoothing_window", 5)),
            confidence_threshold=float(config.get("confidence_threshold", 0.55)),
            jitter_pixels=float(config.get("jitter_pixels", 1.0)),
            min_area_change_ratio=float(config.get("min_area_change_ratio", 0.02)),
        )

    def _filtered(self, deltas: np.ndarray, threshold: float) -> np.ndarray:
        if deltas.size == 0:
            return deltas
        mask = np.abs(deltas) >= threshold
        return deltas[mask]

    def _recent_trend(self, values: np.ndarray) -> float:
        if values.size == 0:
            return 0.0
        window = values[-self.smoothing_window :]
        return float(window.mean())

    def _votes(self, vertical_deltas: np.ndarray, area_deltas: np.ndarray, current_area: float) -> list[int]:
        votes: list[int] = []
        filtered_vertical = self._filtered(vertical_deltas, self.jitter_pixels)
        area_threshold = max(self.min_area_change_ratio * max(current_area, 1.0), 1.0)
        filtered_area = self._filtered(area_deltas, area_threshold)

        for delta in filtered_vertical:
            votes.append(1 if delta > 0 else -1)
        for delta in filtered_area:
            votes.append(1 if delta > 0 else -1)
        return votes

    def _confidence(self, score: float, vote_count: int) -> float:
        if vote_count == 0:
            return 0.0
        normalized = np.tanh(abs(score))
        density = min(1.0, vote_count / max(1, self.min_track_length))
        return float(normalized * density)

    def _evict_stale_history(self, now: float) -> None:
        stale = [tid for tid, ts in self._history_ts.items() if now - ts > self.history_ttl_seconds]
        for tid in stale:
            self._history.pop(tid, None)
            self._history_ts.pop(tid, None)

    def update(self, track_id: int, bbox: list[int]) -> Dict[str, str]:
        if not bbox or len(bbox) != 4:
            return {"direction": self.UNKNOWN}

        width = max(1.0, float(bbox[2] - bbox[0]))
        height = max(1.0, float(bbox[3] - bbox[1]))
        center_y = (float(bbox[1]) + float(bbox[3])) / 2.0
        area = width * height

        now = time.monotonic()
        self._history_ts[track_id] = now
        if now - self._last_evict > self._EVICT_INTERVAL:
            self._evict_stale_history(now)
            self._last_evict = now

        history = self._history.setdefault(track_id, deque(maxlen=self.history_size))
        history.append((center_y, area))

        if len(history) < self.min_track_length:
            return {"direction": self.UNKNOWN}

        centers = np.array([item[0] for item in history], dtype=float)
        areas = np.array([item[1] for item in history], dtype=float)
        vertical_deltas = np.diff(centers)
        area_deltas = np.diff(areas)

        trend_vertical = self._recent_trend(vertical_deltas)
        trend_area = self._recent_trend(area_deltas)

        votes = self._votes(vertical_deltas, area_deltas, areas[-1])
        if not votes:
            return {"direction": self.UNKNOWN}

        score = float(np.mean(votes)) * 0.7 + (np.sign(trend_area) if trend_area != 0 else 0.0) * 0.3
        confidence = self._confidence(score, len(votes))

        if confidence < self.confidence_threshold:
            return {"direction": self.UNKNOWN}

        direction = self.APPROACHING if score >= 0 else self.RECEDING
        return {"direction": direction}


class ANPRPipeline:
    """Основной класс распознавания."""

    def __init__(
        self,
        recognizer: BatchRecognizer,
        best_shots: int,
        cooldown_seconds: int = 0,
        min_confidence: float = 0.6,
        postprocessor: Optional[PlatePostProcessor] = None,
        direction_config: Optional[Dict[str, float | int]] = None,
        max_ocr_attempts: int = 15,
        max_consecutive_empty_ocr: int = 5,
        channel_id: int = 0,
        channel_name: str = "",
    ) -> None:
        self.recognizer = recognizer
        self._channel_label = "Канал {} (id={})".format(
            channel_name or f"Канал {channel_id}", channel_id
        )
        self.aggregator = TrackAggregator(
            best_shots, max_ocr_attempts=max_ocr_attempts,
            channel_label=self._channel_label,
            max_consecutive_empty_ocr=max_consecutive_empty_ocr,
        )
        self.cooldown_seconds = max(0, cooldown_seconds)
        self.min_confidence = max(0.0, min(1.0, min_confidence))
        self._last_seen: Dict[str, float] = {}
        self.postprocessor = postprocessor
        self.preprocessor = PlatePreprocessor()
        self.direction_estimator = TrackDirectionEstimator.from_config(direction_config or {})

    def _on_cooldown(self, plate: str) -> bool:
        now = time.monotonic()
        if self.cooldown_seconds > 0:
            threshold = self.cooldown_seconds * 2
            stale = [p for p, ts in self._last_seen.items() if now - ts > threshold]
            for p in stale:
                del self._last_seen[p]
        last_seen = self._last_seen.get(plate)
        if last_seen is None:
            return False
        return (now - last_seen) < self.cooldown_seconds

    def _touch_plate(self, plate: str) -> None:
        self._last_seen[plate] = time.monotonic()

    def process_frame(self, frame: np.ndarray, detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        plate_inputs: List[np.ndarray] = []
        detection_indices: List[int] = []

        for idx, detection in enumerate(detections):
            track_id = detection.get("track_id")

            # Skip all OCR work for finalized tracks (consensus reached or
            # budget exhausted).  This is the main CPU-saving path.
            # Direction is only computed for the rare unreadable-emit case
            # (which produces an event); plain finalized tracks are skipped
            # entirely, saving numpy direction computation per frame.
            if track_id is not None and not self.aggregator.should_process(track_id):
                detection["plate_image"] = None
                if self.aggregator.should_emit_unreadable(track_id):
                    detection["text"] = "Нечитаемо"
                    detection["unreadable"] = True
                    detection["confidence"] = 0.0
                    if self.direction_estimator:
                        detection.update(self.direction_estimator.update(int(track_id), detection.get("bbox", [])))
                    else:
                        detection.setdefault("direction", TrackDirectionEstimator.UNKNOWN)
                else:
                    detection["text"] = ""
                continue

            if self.direction_estimator and track_id is not None:
                detection.update(self.direction_estimator.update(int(track_id), detection.get("bbox", [])))
            else:
                detection.setdefault("direction", TrackDirectionEstimator.UNKNOWN)

            x1, y1, x2, y2 = detection["bbox"]
            roi = frame[y1:y2, x1:x2]
            detection["plate_image"] = None

            if roi.size > 0:
                processed_plate = self.preprocessor.preprocess(roi)

                if processed_plate.size > 0:
                    plate_inputs.append(processed_plate)
                    detection_indices.append(idx)

        batch_results = self.recognizer.recognize_batch(plate_inputs)

        for detection_idx, (current_text, confidence) in zip(detection_indices, batch_results):
            detection = detections[detection_idx]
            track_id = detection.get("track_id")

            if track_id is not None:
                # Pass empty text for low-confidence results so the attempt
                # is counted but no invalid candidate pollutes the bucket.
                effective_text = current_text if confidence >= self.min_confidence else ""
                result = self.aggregator.add_result(track_id, effective_text, confidence)
                result_type = self.aggregator.last_result_type
                detection["text"] = result
                detection["confidence"] = confidence
                if confidence < self.min_confidence:
                    detection["unreadable"] = True

                # ALL mode: log every OCR attempt.
                attempts = self.aggregator.get_track_attempts(track_id)
                logger.debug(
                    "%s, трек %d: OCR попытка %d/%d, кандидат \"%s\", confidence=%.2f.",
                    self._channel_label,
                    track_id,
                    attempts,
                    self.aggregator.max_ocr_attempts,
                    current_text or "(пусто)",
                    confidence,
                )

                # Budget just exhausted with no valid plate.
                if not result and self.aggregator.should_emit_unreadable(track_id):
                    detection["text"] = "Нечитаемо"
                    detection["unreadable"] = True
            else:
                # Untracked detection — no aggregation available.
                if confidence < self.min_confidence:
                    detection["text"] = "Нечитаемо"
                    detection["unreadable"] = True
                    detection["confidence"] = confidence
                    continue
                detection["text"] = current_text
                detection["confidence"] = confidence
                result_type = ""

            # Post-processing: only for real plate texts, not unreadable markers.
            if self.postprocessor and detection.get("text") and not detection.get("unreadable"):
                processed = self.postprocessor.process(detection["text"])
                detection["original_text"] = detection.get("text")
                detection["country"] = processed.country
                detection["format"] = processed.format_name
                detection["validated"] = processed.is_valid

                if processed.is_valid:
                    detection["text"] = processed.plate
                    if processed.plate_display:
                        detection["plate_display"] = processed.plate_display
                    # ALL mode: log validation success.
                    logger.debug(
                        "%s, трек %d: валидация пройдена, страна/регион \"%s\", шаблон \"%s\".",
                        self._channel_label,
                        track_id if track_id is not None else -1,
                        processed.country or "N/A",
                        processed.format_name or "N/A",
                    )
                    # INFO: budget exhausted, but candidate passed validation.
                    if result_type == "budget_best":
                        logger.info(
                            "%s, трек %d: лимит OCR попыток исчерпан (%d). "
                            "Лучший кандидат: \"%s\". Номер подтверждён валидацией.",
                            self._channel_label,
                            track_id,
                            self.aggregator.get_track_attempts(track_id),
                            processed.plate,
                        )
                else:
                    # ALL mode: log validation failure.
                    logger.debug(
                        "%s, трек %d: валидация не пройдена, кандидат \"%s\" "
                        "не соответствует ни одному шаблону.",
                        self._channel_label,
                        track_id if track_id is not None else -1,
                        processed.original,
                    )
                    detection["text"] = ""
                    if track_id is not None:
                        self.aggregator.reset(track_id)
                        # If budget is now exhausted after reset, emit unreadable
                        # immediately rather than waiting for next frame.
                        if self.aggregator.should_emit_unreadable(track_id):
                            detection["text"] = "Нечитаемо"
                            detection["unreadable"] = True
                            # INFO: budget exhausted + validation failed.
                            logger.info(
                                "%s, трек %d: лимит OCR попыток исчерпан (%d). "
                                "Лучший кандидат: \"%s\". В события не добавлен: "
                                "номер не прошёл валидацию ни по одному шаблону страны/региона.",
                                self._channel_label,
                                track_id,
                                self.aggregator.get_track_attempts(track_id),
                                processed.original,
                            )

            if self.cooldown_seconds > 0 and detection.get("text") and not detection.get("unreadable"):
                if self._on_cooldown(detection["text"]):
                    detection["text"] = ""
                else:
                    self._touch_plate(detection["text"])
        return detections
