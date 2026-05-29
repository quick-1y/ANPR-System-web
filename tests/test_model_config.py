from anpr.model_config import AnprModelConfig, OCR_ALPHABET, OCR_IMAGE_HEIGHT, OCR_IMAGE_WIDTH


class TestAnprModelConfig:
    def test_from_settings_uses_hardcoded_ocr_contract(self):
        config = AnprModelConfig.from_settings(
            {
                "yolo_model_path": "anpr/models/yolo/best.pt",
                "ocr_model_path": "anpr/models/ocr_crnn/crnn_ocr_model_int8_fx.pth",
                "device": "cpu",
            },
            {"confidence_threshold": 0.5, "bbox_padding_ratio": 0.08, "min_padding_pixels": 2},
        )

        assert config.ocr_height == OCR_IMAGE_HEIGHT
        assert config.ocr_width == OCR_IMAGE_WIDTH
        assert config.ocr_alphabet == OCR_ALPHABET
