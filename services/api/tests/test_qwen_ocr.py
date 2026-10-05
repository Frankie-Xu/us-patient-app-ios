from __future__ import annotations

import base64
import json
import unittest
from io import BytesIO
from urllib.error import HTTPError

from services.api.qwen_ocr import Qwen35OCRProvider, QwenOCRError, QwenOCRSettings


class _Response:
    status = 200

    def __init__(self, body: dict[str, object]) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class QwenOCRTests(unittest.TestCase):
    def settings(self) -> QwenOCRSettings:
        return QwenOCRSettings(api_key="k", base_url="https://workspace.example/compatible-mode/v1")

    def test_image_request_uses_server_key_and_qwen_model(self) -> None:
        captured: dict[str, object] = {}

        def opener(request, *, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.headers.get("Authorization")
            captured["timeout"] = timeout
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _Response({"choices": [{"message": {"content": "synthetic OCR text"}}]})

        provider = Qwen35OCRProvider(self.settings(), opener=opener)
        result = provider.extract(b"png-bytes", "image/png", filename="synthetic.png")

        self.assertEqual(result, "synthetic OCR text")
        self.assertEqual(captured["url"], "https://workspace.example/compatible-mode/v1/chat/completions")
        self.assertEqual(captured["authorization"], "Bearer k")
        body = captured["body"]
        self.assertEqual(body["model"], "qwen3.5-ocr")
        image = body["messages"][0]["content"][0]["image_url"]["url"]
        self.assertEqual(image, "data:image/png;base64," + base64.b64encode(b"png-bytes").decode("ascii"))
        self.assertNotIn("Bearer k", json.dumps(body))

    def test_provider_configuration_requires_server_credentials_and_endpoint(self) -> None:
        with self.assertRaises(QwenOCRError) as missing:
            QwenOCRSettings.from_environment({"DASHSCOPE_API_KEY": "only-key"})
        self.assertEqual(missing.exception.code, "OCR_CONFIGURATION_INVALID")
        self.assertFalse(missing.exception.retryable)
        with self.assertRaises(QwenOCRError) as insecure:
            QwenOCRSettings.from_environment(
                {"DASHSCOPE_API_KEY": "k", "DASHSCOPE_BASE_URL": "http://workspace.example"}
            )
        self.assertEqual(insecure.exception.code, "OCR_CONFIGURATION_INVALID")
        self.assertFalse(insecure.exception.retryable)

    def test_pdf_fails_closed_until_responses_file_path_is_configured(self) -> None:
        provider = Qwen35OCRProvider(self.settings(), opener=lambda *_args, **_kwargs: self.fail("network must not be called"))
        with self.assertRaises(QwenOCRError) as error:
            provider.extract(b"synthetic-pdf", "application/pdf", filename="synthetic.pdf")
        self.assertEqual(error.exception.code, "OCR_MEDIA_UNSUPPORTED")
        self.assertFalse(error.exception.retryable)

    def test_throttle_is_retryable_without_exposing_provider_body(self) -> None:
        def opener(request, *, timeout):
            del request, timeout
            raise HTTPError("https://workspace.example", 429, "throttled", {}, BytesIO(b"sensitive provider body"))

        provider = Qwen35OCRProvider(self.settings(), opener=opener)
        with self.assertRaises(QwenOCRError) as error:
            provider.extract(b"png-bytes", "image/png")
        self.assertEqual(error.exception.code, "OCR_PROVIDER_RETRYABLE")
        self.assertTrue(error.exception.retryable)


if __name__ == "__main__":
    unittest.main()
