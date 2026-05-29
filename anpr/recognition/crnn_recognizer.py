# /anpr/recognition/crnn_recognizer.py
"""Обертка для квантованной CRNN-модели."""

from __future__ import annotations

from typing import Dict, List, Tuple

import cv2
import numpy as np

import torch
import torch.ao.quantization.quantize_fx as quantize_fx
from torch.ao.quantization import QConfigMapping

from anpr.model_config import OCR_ALPHABET, OCR_IMAGE_HEIGHT, OCR_IMAGE_WIDTH
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
        ocr_height: int = OCR_IMAGE_HEIGHT,
        ocr_width: int = OCR_IMAGE_WIDTH,
        ocr_alphabet: str = OCR_ALPHABET,
    ) -> None:
        target_device = device
        if device.type != "cpu":
            logger.warning(
                "Квантованная OCR-модель поддерживает только CPU. Переключаемся на CPU вместо %s.", device
            )
            target_device = torch.device("cpu")

        self.device = target_device
        self._ocr_height = ocr_height
        self._ocr_width = ocr_width
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

    def _preprocess(self, img: np.ndarray) -> torch.Tensor:
        if img.ndim == 3 and img.shape[2] == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        elif img.ndim == 3 and img.shape[2] == 1:
            gray = img[:, :, 0]
        else:
            gray = img
        resized = cv2.resize(gray, (self._ocr_width, self._ocr_height), interpolation=cv2.INTER_LINEAR)
        tensor = torch.from_numpy(resized).float().unsqueeze(0) / 255.0
        tensor = (tensor - 0.5) / 0.5
        return tensor

    @torch.no_grad()
    def recognize_batch(self, plate_images: List[np.ndarray]) -> List[Tuple[str, float]]:
        """Распознаёт батч изображений номерных знаков."""

        if not plate_images:
            return []

        batch = torch.stack([self._preprocess(img) for img in plate_images]).to(self.device)
        preds = self.model(batch)
        return self._decode_batch(preds)

    def _decode_batch(self, log_probs: torch.Tensor) -> List[Tuple[str, float]]:
        # log_probs: [time_steps, batch_size, num_classes]
        batch_probs = log_probs.permute(1, 0, 2)  # [batch, time, classes]

        # Vectorised: compute argmax and exp(max) over all positions at once
        indices = batch_probs.argmax(dim=-1)  # [batch, time]
        confs = batch_probs.max(dim=-1).values.exp()  # [batch, time]

        # Single device-to-host copy for the entire batch
        indices_np = indices.cpu().numpy()
        confs_np = confs.cpu().numpy()

        results: List[Tuple[str, float]] = []
        for b in range(len(indices_np)):
            decoded_chars: List[str] = []
            char_confidences: List[float] = []
            last_char_idx = 0

            for t in range(len(indices_np[b])):
                char_idx = int(indices_np[b, t])
                char_conf = float(confs_np[b, t])

                if char_idx != 0 and char_idx != last_char_idx:
                    decoded_chars.append(self.int_to_char.get(char_idx, ""))
                    char_confidences.append(char_conf)

                last_char_idx = char_idx

            text = "".join(decoded_chars)
            avg_confidence = sum(char_confidences) / len(char_confidences) if char_confidences else 0.0
            results.append((text, avg_confidence))

        return results
