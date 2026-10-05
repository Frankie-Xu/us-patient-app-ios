from __future__ import annotations

import base64
import json
import unittest
from io import BytesIO
from urllib.error import HTTPError, URLError

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
        return QwenOCRSettings(api_key="sk-" + "k" * 13, base_url="https://workspace.example/compatible-mode/v1")

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
        self.assertEqual(captured["authorization"], "Bearer sk-" + "k" * 13)
        body = captured["body"]
        self.assertEqual(body["model"], "qwen3.5-ocr")
        image = body["messages"][0]["content"][0]["image_url"]["url"]
        self.assertEqual(image, "data:image/png;base64," + base64.b64encode(b"png-bytes").decode("ascii"))
        self.assertNotIn("Bearer sk-", json.dumps(body))

    def test_provider_configuration_requires_server_credentials_and_endpoint(self) -> None:
        with self.assertRaises(QwenOCRError) as missing:
            QwenOCRSettings.from_environment({"DASHSCOPE_API_KEY": "only-key"})
        self.assertEqual(missing.exception.code, "OCR_CONFIGURATION_INVALID")
        self.assertFalse(missing.exception.retryable)
        with self.assertRaises(QwenOCRError) as insecure:
            QwenOCRSettings.from_environment(
                {"DASHSCOPE_API_KEY": "sk-" + "k" * 13, "DASHSCOPE_BASE_URL": "http://workspace.example", "DASHSCOPE_MODEL": "qwen-vl-ocr"}
            )
        self.assertEqual(insecure.exception.code, "OCR_CONFIGURATION_INVALID")
        self.assertFalse(insecure.exception.retryable)

    def test_configuration_rejects_missing_model_malformed_key_and_endpoint_credentials(self) -> None:
        cases = (
            {"DASHSCOPE_API_KEY": "sk-" + "k" * 13, "DASHSCOPE_BASE_URL": "https://workspace.example"},
            {"DASHSCOPE_API_KEY": "not-a-provider-key", "DASHSCOPE_BASE_URL": "https://workspace.example", "DASHSCOPE_MODEL": "qwen-vl-ocr"},
            {"DASHSCOPE_API_KEY": "sk-" + "k" * 13, "DASHSCOPE_BASE_URL": "https://user:password@workspace.example", "DASHSCOPE_MODEL": "qwen-vl-ocr"},
        )
        for values in cases:
            with self.assertRaises(QwenOCRError) as error:
                QwenOCRSettings.from_environment(values)
            self.assertEqual(error.exception.code, "OCR_CONFIGURATION_INVALID")
            self.assertFalse(error.exception.retryable)

    def test_configuration_accepts_provider_key_with_dots(self) -> None:
        values = {
            "DASHSCOPE_API_KEY": "sk-" + "ab.cd_ef-12" * 2,
            "DASHSCOPE_BASE_URL": "https://workspace.example/compatible-mode/v1",
            "DASHSCOPE_MODEL": "qwen-vl-ocr",
        }
        settings = QwenOCRSettings.from_environment(values)
        self.assertEqual(settings.model, "qwen-vl-ocr")

    def test_pdf_is_rasterized_server_side_and_each_page_uses_image_ocr(self) -> None:
        responses = iter(
            [
                _Response({"choices": [{"message": {"content": "page one"}}]}),
                _Response({"choices": [{"message": {"content": "page two"}}]}),
            ]
        )
        requests: list[dict[str, object]] = []

        def opener(request, *, timeout):
            del timeout
            requests.append(json.loads(request.data.decode("utf-8")))
            return next(responses)

        provider = Qwen35OCRProvider(
            self.settings(),
            opener=opener,
            rasterizer=lambda content: [b"png-page-one", b"png-page-two"] if content == b"synthetic-pdf" else [],
        )
        result = provider.extract(b"synthetic-pdf", "application/pdf", filename="synthetic.pdf")

        self.assertEqual(result, "page one\n\f\npage two")
        self.assertEqual(len(requests), 2)
        self.assertTrue(requests[0]["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_pdf_rasterizer_failure_is_terminal_and_bounded(self) -> None:
        def rasterizer(_content: bytes) -> list[bytes]:
            raise QwenOCRError("OCR_PDF_RASTERIZE_FAILED", retryable=False)

        provider = Qwen35OCRProvider(
            self.settings(),
            opener=lambda *_args, **_kwargs: self.fail("network must not be called"),
            rasterizer=rasterizer,
        )
        with self.assertRaises(QwenOCRError) as error:
            provider.extract(b"synthetic-pdf", "application/pdf")
        self.assertEqual(error.exception.code, "OCR_PDF_RASTERIZE_FAILED")
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

    def test_server_error_is_retryable_and_body_is_not_exposed(self) -> None:
        def opener(request, *, timeout):
            del request, timeout
            raise HTTPError("https://workspace.example", 503, "upstream", {}, BytesIO(b"private response body"))

        provider = Qwen35OCRProvider(self.settings(), opener=opener)
        with self.assertRaises(QwenOCRError) as error:
            provider.extract(b"png-bytes", "image/png")
        self.assertEqual(error.exception.code, "OCR_PROVIDER_RETRYABLE")
        self.assertTrue(error.exception.retryable)
        self.assertNotIn("private response body", str(error.exception))

    def test_client_error_is_terminal(self) -> None:
        def opener(request, *, timeout):
            del request, timeout
            raise HTTPError("https://workspace.example", 400, "bad request", {}, BytesIO(b"private provider body"))

        provider = Qwen35OCRProvider(self.settings(), opener=opener)
        with self.assertRaises(QwenOCRError) as error:
            provider.extract(b"png-bytes", "image/png")
        self.assertEqual(error.exception.code, "OCR_PROVIDER_REJECTED")
        self.assertFalse(error.exception.retryable)
        self.assertNotIn("private provider body", str(error.exception))

    def test_network_failure_is_retryable(self) -> None:
        def opener(request, *, timeout):
            del request, timeout
            raise URLError("private network detail")

        provider = Qwen35OCRProvider(self.settings(), opener=opener)
        with self.assertRaises(QwenOCRError) as error:
            provider.extract(b"png-bytes", "image/png")
        self.assertEqual(error.exception.code, "OCR_PROVIDER_UNAVAILABLE")
        self.assertTrue(error.exception.retryable)

    def test_empty_invalid_and_non_json_responses_are_terminal(self) -> None:
        responses = (
            _Response({"choices": []}),
            _Response({"choices": [{"message": {"content": ""}}]}),
        )
        for response in responses:
            provider = Qwen35OCRProvider(self.settings(), opener=lambda *_args, response=response, **_kwargs: response)
            with self.assertRaises(QwenOCRError) as error:
                provider.extract(b"png-bytes", "image/png")
            self.assertEqual(error.exception.code, "OCR_EMPTY_RESULT")
            self.assertFalse(error.exception.retryable)

        class InvalidResponse(_Response):
            def __init__(self) -> None:
                self._body = b"not-json"

        provider = Qwen35OCRProvider(self.settings(), opener=lambda *_args, **_kwargs: InvalidResponse())
        with self.assertRaises(QwenOCRError) as error:
            provider.extract(b"png-bytes", "image/png")
        self.assertEqual(error.exception.code, "OCR_PROVIDER_INVALID_RESPONSE")
        self.assertFalse(error.exception.retryable)


if __name__ == "__main__":
    unittest.main()
