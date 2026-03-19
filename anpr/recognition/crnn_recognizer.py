# /anpr/recognition/crnn_recognizer.py
"""Обертка для квантованной CRNN-модели."""

from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

import numpy as np

import torch
import torch.ao.quantization.quantize_fx as quantize_fx
from torch.ao.quantization import QConfigMapping
from torchvision import transforms

from anpr.recognition.crnn import CRNN
from common.logging import get_logger

logger = get_logger(__name__)


class CRNNRecognizer:
    """Подготовка, загрузка и инференс CRNN."""

    def __init__(
        self,
        model_path: str,
        device: torch.device,
        *,
        ocr_height: int = 32,
        ocr_width: int = 128,
        ocr_alphabet: str = "",
    ) -> None:
        target_device = device
        if device.type != "cpu":
            logger.warning(
                "Квантованная OCR-модель поддерживает только CPU. Переключаемся на CPU вместо %s.", device
            )
            target_device = torch.device("cpu")

        self.device = target_device
        self.transform = transforms.Compose(
            [
                transforms.ToPILImage(),
                transforms.Grayscale(),
                transforms.Resize((ocr_height, ocr_width)),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.5], std=[0.5]),
            ]
        )
        self.int_to_char: Dict[int, str] = {i + 1: char for i, char in enumerate(ocr_alphabet)}
        self.int_to_char[0] = ""

        num_classes = len(ocr_alphabet) + 1

        model_to_load = CRNN(num_classes).eval()
        qconfig_mapping = QConfigMapping().set_global(torch.ao.quantization.get_default_qconfig("fbgemm"))
        example_inputs = (torch.randn(1, 1, ocr_height, ocr_width),)
        model_prepared = quantize_fx.prepare_fx(model_to_load, qconfig_mapping, example_inputs)
        model_quantized = quantize_fx.convert_fx(model_prepared)

        model_quantized.load_state_dict(torch.load(model_path, map_location=self.device))
        self.model = model_quantized.to(self.device)
        logger.info("Распознаватель OCR (INT8) успешно загружен (model=%s, device=%s)", model_path, self.device)

    @torch.no_grad()
    def recognize_batch(self, plate_images: Iterable[np.ndarray]) -> List[Tuple[str, float]]:
        """Распознаёт батч изображений номерных знаков."""

        plate_images = list(plate_images)
        if not plate_images:
            return []

        batch = torch.stack([self.transform(img) for img in plate_images]).to(self.device)
        preds = self.model(batch)
        return self._decode_batch(preds)

    def _decode_batch(self, log_probs: torch.Tensor) -> List[Tuple[str, float]]:
        batch_probs = log_probs.permute(1, 0, 2)          # [batch, time, classes]
        char_indices = batch_probs.argmax(dim=-1)           # [batch, time]
        char_confs = batch_probs.exp().max(dim=-1).values   # [batch, time]
        # Single device-to-host transfer for the entire batch
        indices_np = char_indices.cpu().numpy()             # [batch, time]
        confs_np = char_confs.cpu().numpy()                 # [batch, time]

        results: List[Tuple[str, float]] = []
        for b in range(indices_np.shape[0]):
            chars: List[str] = []
            confidences: List[float] = []
            prev = 0
            for t, idx in enumerate(indices_np[b]):
                if idx != 0 and idx != prev:
                    chars.append(self.int_to_char.get(int(idx), ""))
                    confidences.append(float(confs_np[b, t]))
                prev = idx
            text = "".join(chars)
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
            results.append((text, avg_conf))
        return results
