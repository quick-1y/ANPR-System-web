#!/usr/bin/env python3
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Dict, Optional, Tuple

from anpr.detection.yolo_detector import YOLODetector
from anpr.pipeline.anpr_pipeline import ANPRPipeline
from anpr.postprocessing.country_config import CountryConfigLoader
from anpr.postprocessing.validator import PlatePostProcessor
from anpr.recognition.crnn_recognizer import CRNNRecognizer

if TYPE_CHECKING:
    import os
    from anpr.model_config import AnprModelConfig


_RECOGNIZER_LOCK = threading.RLock()
_RECOGNIZER_INITIALIZING = False
_RECOGNIZER_READY = threading.Event()
_RECOGNIZER_SINGLETON: Optional[CRNNRecognizer] = None


class _FallbackRecognizer:
    """Неблокирующая заглушка, пока OCR ещё не инициализирован."""

    def recognize_batch(self, _plate_images):
        return []


_NOOP_RECOGNIZER = _FallbackRecognizer()


def _get_shared_recognizer(model_config: "AnprModelConfig") -> CRNNRecognizer:
    """Lazily initializes a single OCR recognizer instance for all pipelines.

    CRNN quantization with ``prepare_fx`` is not thread-safe, so creating the
    recognizer concurrently for multiple channels can crash.  By guarding
    initialization with a lock and reusing the instance across pipelines, we
    avoid the race while keeping inference stateless and reusable.
    """

    global _RECOGNIZER_INITIALIZING, _RECOGNIZER_SINGLETON

    if _RECOGNIZER_SINGLETON is None and not _RECOGNIZER_INITIALIZING:
        with _RECOGNIZER_LOCK:
            if _RECOGNIZER_SINGLETON is None and not _RECOGNIZER_INITIALIZING:
                _RECOGNIZER_INITIALIZING = True
                _RECOGNIZER_READY.clear()
                _captured_config = model_config

                def _init() -> None:
                    global _RECOGNIZER_INITIALIZING, _RECOGNIZER_SINGLETON

                    try:
                        cfg = _captured_config
                        _RECOGNIZER_SINGLETON = CRNNRecognizer(
                            cfg.ocr_model_path,
                            cfg.device,
                            ocr_height=cfg.ocr_height,
                            ocr_width=cfg.ocr_width,
                            ocr_alphabet=cfg.ocr_alphabet,
                        )
                    finally:
                        _RECOGNIZER_INITIALIZING = False
                        _RECOGNIZER_READY.set()

                threading.Thread(target=_init, daemon=True).start()

    if not _RECOGNIZER_READY.wait(timeout=0.1):
        _RECOGNIZER_READY.wait()

    return _RECOGNIZER_SINGLETON or _NOOP_RECOGNIZER


def _build_postprocessor(config: Dict[str, object]) -> PlatePostProcessor:
    import os
    config_dir = str(config.get("config_dir") or "anpr/countries")
    enabled_countries = config.get("enabled_countries")
    loader = CountryConfigLoader(os.path.abspath(config_dir))
    loader.ensure_dir()
    return PlatePostProcessor(loader, enabled_countries)


def build_components(
    best_shots: int,
    cooldown_seconds: int,
    min_confidence: float,
    model_config: "Optional[AnprModelConfig]" = None,
    plate_config: Optional[Dict[str, object]] = None,
    direction_config: Optional[Dict[str, object]] = None,
    min_plate_size: Optional[Dict[str, int]] = None,
    max_plate_size: Optional[Dict[str, int]] = None,
    size_filter_enabled: bool = True,
    max_ocr_attempts: int = 15,
) -> Tuple[ANPRPipeline, YOLODetector]:
    """Создаёт независимые компоненты пайплайна (детектор, OCR и агрегация)."""

    if model_config is None:
        # Fallback for callers that have not yet migrated to passing model_config.
        # This path should not be reached in normal operation.
        from anpr.model_config import AnprModelConfig
        model_config = AnprModelConfig(yolo_model_path="", ocr_model_path="")

    detector = YOLODetector(
        model_config.yolo_model_path,
        model_config.device,
        min_plate_size=min_plate_size,
        max_plate_size=max_plate_size,
        size_filter_enabled=size_filter_enabled,
        detection_confidence_threshold=model_config.detection_confidence_threshold,
        bbox_padding_ratio=model_config.bbox_padding_ratio,
        min_padding_pixels=model_config.min_padding_pixels,
    )
    recognizer = _get_shared_recognizer(model_config)
    postprocessor = _build_postprocessor(plate_config or {})
    pipeline = ANPRPipeline(
        recognizer,
        best_shots,
        cooldown_seconds,
        min_confidence=min_confidence,
        postprocessor=postprocessor,
        direction_config=direction_config,
        max_ocr_attempts=max_ocr_attempts,
    )
    return pipeline, detector
