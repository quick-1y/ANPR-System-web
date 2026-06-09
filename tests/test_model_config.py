from anpr.model_config import (
    AnprModelConfig,
    BBOX_PADDING_RATIO,
    DETECTION_CONFIDENCE_THRESHOLD,
    MIN_PADDING_PIXELS,
    OCR_ALPHABET,
    OCR_IMAGE_HEIGHT,
    OCR_IMAGE_WIDTH,
)


class TestAnprModelConfig:
    def test_from_settings_uses_hardcoded_model_contracts(self):
        config = AnprModelConfig.from_settings(
            {
                "yolo_model_path": "anpr/models/yolo/best.pt",
                "ocr_model_path": "anpr/models/ocr_crnn/crnn_ocr_model_int8_fx.pth",
                "device": "cpu",
            },
        )

        assert config.ocr_height == OCR_IMAGE_HEIGHT
        assert config.ocr_width == OCR_IMAGE_WIDTH
        assert config.ocr_alphabet == OCR_ALPHABET
        assert config.detection_confidence_threshold == DETECTION_CONFIDENCE_THRESHOLD
        assert config.bbox_padding_ratio == BBOX_PADDING_RATIO
        assert config.min_padding_pixels == MIN_PADDING_PIXELS
