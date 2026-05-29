from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import torch

# Контракт текущей OCR-модели: менять только вместе с переобученными весами.
OCR_IMAGE_HEIGHT = 32
OCR_IMAGE_WIDTH = 128
OCR_ALPHABET = "0123456789ABCEHKMOPTXY"


@dataclass
class AnprModelConfig:
    """Plain-data configuration for ANPR model components.

    Constructed by AppContainer from SettingsManager and passed down into
    ChannelProcessor → build_components().  The anpr/ package itself has no
    dependency on SettingsManager; all settings resolution happens before this
    object is created.
    """

    yolo_model_path: str
    ocr_model_path: str
    device_name: str = "cpu"
    # OCR model contract
    ocr_height: int = OCR_IMAGE_HEIGHT
    ocr_width: int = OCR_IMAGE_WIDTH
    ocr_alphabet: str = OCR_ALPHABET
    # Detector
    detection_confidence_threshold: float = 0.5
    bbox_padding_ratio: float = 0.08
    min_padding_pixels: int = 2

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
    def from_settings(
        cls,
        model_settings: Dict[str, Any],
        detector_settings: Dict[str, Any],
    ) -> "AnprModelConfig":
        return cls(
            yolo_model_path=str(model_settings.get("yolo_model_path", "")),
            ocr_model_path=str(model_settings.get("ocr_model_path", "")),
            device_name=str(model_settings.get("device") or "cpu"),
            ocr_height=OCR_IMAGE_HEIGHT,
            ocr_width=OCR_IMAGE_WIDTH,
            ocr_alphabet=OCR_ALPHABET,
            detection_confidence_threshold=float(detector_settings.get("confidence_threshold", 0.5)),
            bbox_padding_ratio=float(detector_settings.get("bbox_padding_ratio", 0.08)),
            min_padding_pixels=int(detector_settings.get("min_padding_pixels", 2)),
        )


__all__ = ["AnprModelConfig", "OCR_ALPHABET", "OCR_IMAGE_HEIGHT", "OCR_IMAGE_WIDTH"]
