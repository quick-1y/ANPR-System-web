import pytest

from anpr.model_config import (
    AnprModelConfig,
    BBOX_PADDING_RATIO,
    DETECTION_CONFIDENCE_THRESHOLD,
    MIN_PADDING_PIXELS,
    OCR_ALPHABET,
    OCR_IMAGE_HEIGHT,
    OCR_IMAGE_WIDTH,
)
from config.env_settings import EnvConfigError, load_env_config, verify_model_files


class TestAnprModelConfig:
    def test_from_env_reads_paths_and_device_and_keeps_model_contracts(self):
        env = load_env_config({"ANPR_YOLO_MODEL_PATH": "w/y.pt", "ANPR_OCR_MODEL_PATH": "w/o.pth", "ANPR_DEVICE": "CUDA"})
        config = AnprModelConfig.from_env(env)

        assert (config.yolo_model_path, config.ocr_model_path, config.device_name) == ("w/y.pt", "w/o.pth", "cuda")
        assert config.ocr_height == OCR_IMAGE_HEIGHT
        assert config.ocr_width == OCR_IMAGE_WIDTH
        assert config.ocr_alphabet == OCR_ALPHABET
        assert config.detection_confidence_threshold == DETECTION_CONFIDENCE_THRESHOLD
        assert config.bbox_padding_ratio == BBOX_PADDING_RATIO
        assert config.min_padding_pixels == MIN_PADDING_PIXELS

    def test_defaults_are_the_bundled_weights_and_cpu(self):
        config = AnprModelConfig.from_env(load_env_config({}))
        assert config.yolo_model_path == "anpr/models/yolo/best.pt"
        assert config.ocr_model_path == "anpr/models/ocr_crnn/crnn_ocr_model_int8_fx.pth"
        assert config.device_name == "cpu"

    def test_threshold_comes_from_the_operational_setting(self):
        config = AnprModelConfig.from_env(load_env_config({}), detection_confidence_threshold=0.7)
        assert config.detection_confidence_threshold == 0.7

    def test_from_settings_is_gone(self):
        assert not hasattr(AnprModelConfig, "from_settings")


class TestModelFilesCheck:
    def test_existing_files_pass(self, tmp_path):
        yolo, ocr = tmp_path / "y.pt", tmp_path / "o.pth"
        yolo.write_bytes(b"x")
        ocr.write_bytes(b"x")
        verify_model_files(load_env_config({"ANPR_YOLO_MODEL_PATH": str(yolo), "ANPR_OCR_MODEL_PATH": str(ocr)}))

    def test_missing_file_gives_a_clear_startup_error_naming_the_variable(self, tmp_path):
        env = load_env_config({"ANPR_YOLO_MODEL_PATH": str(tmp_path / "nope.pt"), "ANPR_OCR_MODEL_PATH": str(tmp_path / "nope.pth")})
        with pytest.raises(EnvConfigError) as exc:
            verify_model_files(env)
        message = str(exc.value)
        assert "ANPR_YOLO_MODEL_PATH" in message and "ANPR_OCR_MODEL_PATH" in message
        assert "nope.pt" in message
