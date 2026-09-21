from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch

# Контракт текущих моделей: менять только вместе с проверенными/переобученными весами.
OCR_IMAGE_HEIGHT = 32
OCR_IMAGE_WIDTH = 128
OCR_ALPHABET = "0123456789ABCEHKMOPTXY"
DETECTION_CONFIDENCE_THRESHOLD = 0.5
BBOX_PADDING_RATIO = 0.08
MIN_PADDING_PIXELS = 2


@dataclass
class AnprModelConfig:
    """Plain-data configuration for ANPR model components.

    Constructed by AppContainer from EnvConfig and passed down into
    ChannelProcessor → build_components().  The anpr/ package itself has no
    dependency on the config layer; all settings resolution happens before this
    object is created.
    """

    yolo_model_path: str
    ocr_model_path: str
    device_name: str = "cpu"
    # OCR model contract
    ocr_height: int = OCR_IMAGE_HEIGHT
    ocr_width: int = OCR_IMAGE_WIDTH
    ocr_alphabet: str = OCR_ALPHABET
    # Detector model contract
    detection_confidence_threshold: float = DETECTION_CONFIDENCE_THRESHOLD
    bbox_padding_ratio: float = BBOX_PADDING_RATIO
    min_padding_pixels: int = MIN_PADDING_PIXELS

    @property
    def device(self) -> torch.device:
        name = str(self.device_name or "cpu").strip().lower()
        if name == "gpu":
            name = "cuda"
        if name.startswith("cuda") and not torch.cuda.is_available():
            return torch.device("cpu")
        try:
            return torch.device(name)
        except (TypeError, ValueError):
            return torch.device("cpu")

    @classmethod
    def from_env(
        cls,
        env: Any,
        detection_confidence_threshold: float = DETECTION_CONFIDENCE_THRESHOLD,
    ) -> "AnprModelConfig":
        """Build from `EnvConfig` (weights paths, device) plus the operational
        `detection.confidence_threshold` from app_settings."""
        return cls(
            yolo_model_path=env.yolo_model_path,
            ocr_model_path=env.ocr_model_path,
            device_name=env.device,
            detection_confidence_threshold=float(detection_confidence_threshold),
        )


__all__ = [
    "AnprModelConfig",
    "BBOX_PADDING_RATIO",
    "DETECTION_CONFIDENCE_THRESHOLD",
    "MIN_PADDING_PIXELS",
    "OCR_ALPHABET",
    "OCR_IMAGE_HEIGHT",
    "OCR_IMAGE_WIDTH",
]
