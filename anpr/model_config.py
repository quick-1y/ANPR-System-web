from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import torch


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
    # OCR
    ocr_height: int = 32
    ocr_width: int = 128
    ocr_alphabet: str = ""
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
        ocr_settings: Dict[str, Any],
        detector_settings: Dict[str, Any],
    ) -> "AnprModelConfig":
        return cls(
            yolo_model_path=str(model_settings.get("yolo_model_path", "")),
            ocr_model_path=str(model_settings.get("ocr_model_path", "")),
            device_name=str(model_settings.get("device") or "cpu"),
            ocr_height=int(ocr_settings.get("img_height", 32)),
            ocr_width=int(ocr_settings.get("img_width", 128)),
            ocr_alphabet=str(ocr_settings.get("alphabet", "")),
            detection_confidence_threshold=float(detector_settings.get("confidence_threshold", 0.5)),
            bbox_padding_ratio=float(detector_settings.get("bbox_padding_ratio", 0.08)),
            min_padding_pixels=int(detector_settings.get("min_padding_pixels", 2)),
        )


__all__ = ["AnprModelConfig"]
