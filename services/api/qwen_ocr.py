"""Server-side Alibaba Cloud Model Studio Qwen3.5-OCR adapter.

The adapter intentionally accepts only an API key supplied to the worker
environment.  iOS clients never call this provider directly.  Network errors
and provider throttling are classified for the existing bounded worker retry;
credentials, prompts, source bytes, and provider responses are never logged.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class QwenOCRError(RuntimeError):
    """Safe provider failure category without including document content."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class QwenOCRSettings:
    api_key: str
    base_url: str
    model: str = "qwen3.5-ocr"
    task: str = "text_recognition"
    timeout_seconds: float = 60.0

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> "QwenOCRSettings":
        values = os.environ if env is None else env
        api_key = str(values.get("DASHSCOPE_API_KEY", "")).strip()
        base_url = str(values.get("DASHSCOPE_BASE_URL", "")).strip().rstrip("/")
        if not api_key or not base_url:
            raise QwenOCRError("OCR_CONFIGURATION_INVALID", retryable=False)
        if not base_url.startswith("https://"):
            raise QwenOCRError("OCR_CONFIGURATION_INVALID", retryable=False)
        try:
            timeout = float(values.get("DASHSCOPE_TIMEOUT_SECONDS", "60"))
        except (TypeError, ValueError) as exc:
            raise QwenOCRError("OCR_CONFIGURATION_INVALID", retryable=False) from exc
        if timeout <= 0:
            raise QwenOCRError("OCR_CONFIGURATION_INVALID", retryable=False)
        model = str(values.get("DASHSCOPE_MODEL", "qwen3.5-ocr")).strip() or "qwen3.5-ocr"
        task = str(values.get("DASHSCOPE_OCR_TASK", "text_recognition")).strip() or "text_recognition"
        return cls(api_key=api_key, base_url=base_url, model=model, task=task, timeout_seconds=timeout)


class Qwen35OCRProvider:
    """Minimal OpenAI-compatible image OCR client for the Worker boundary."""

    provider_name = "aliyun-bailian-qwen3.5-ocr"
    _MAX_IMAGE_BYTES = 20 * 1024 * 1024
    _IMAGE_TYPES = {
        "image/bmp",
        "image/heic",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "image/webp",
    }

    def __init__(self, settings: QwenOCRSettings, *, opener: Callable[..., Any] = urlopen) -> None:
        self.settings = settings
        self._opener = opener

    @classmethod
    def from_environment(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        opener: Callable[..., Any] = urlopen,
    ) -> "Qwen35OCRProvider":
        return cls(QwenOCRSettings.from_environment(env), opener=opener)

    @staticmethod
    def _response_text(payload: Mapping[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        if not isinstance(first, Mapping):
            return ""
        message = first.get("message")
        if not isinstance(message, Mapping):
            return ""
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            chunks = []
            for item in content:
                if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                    chunks.append(item["text"])
            return "".join(chunks).strip()
        return ""

    def extract(self, content: bytes, media_type: str, *, filename: str = "") -> str:
        del filename  # The provider receives the MIME type as the source of truth.
        normalized_type = (media_type or "").lower().split(";", 1)[0].strip()
        if normalized_type not in self._IMAGE_TYPES:
            # PDF requires the Responses API file input or a server-side
            # rasterization step; silently treating it as an image is unsafe.
            raise QwenOCRError("OCR_MEDIA_UNSUPPORTED", retryable=False)
        if not isinstance(content, bytes) or not content:
            raise QwenOCRError("OCR_EMPTY_INPUT", retryable=False)
        if len(content) > self._MAX_IMAGE_BYTES:
            raise QwenOCRError("OCR_INPUT_TOO_LARGE", retryable=False)

        encoded = base64.b64encode(content).decode("ascii")
        data_url = f"data:{normalized_type};base64,{encoded}"
        if self.settings.task == "document_parsing":
            prompt = (
                "Transcribe only the visible text in this medical document image. "
                "Preserve reading order, headings, tables, and line breaks. "
                "Do not infer or add facts. Use [UNCLEAR] for unreadable text."
            )
        elif self.settings.task == "table_parsing":
            prompt = (
                "Transcribe only the visible table text in this medical document image. "
                "Preserve row and column order and mark unreadable cells as [UNCLEAR]. "
                "Do not infer or add facts."
            )
        else:
            prompt = (
                "Extract only the text visible in this medical document image. "
                "Preserve reading order and line breaks. Do not infer or add facts. "
                "Use [UNCLEAR] for unreadable text."
            )
        request_body = {
            "model": self.settings.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                            "min_pixels": 3072,
                            "max_pixels": 8388608,
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        }
        request = Request(
            f"{self.settings.base_url}/chat/completions",
            data=json.dumps(request_body, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.settings.timeout_seconds) as response:
                raw = response.read()
                status = int(getattr(response, "status", 200))
        except HTTPError as exc:
            retryable = exc.code == 429 or exc.code >= 500
            raise QwenOCRError("OCR_PROVIDER_RETRYABLE" if retryable else "OCR_PROVIDER_REJECTED", retryable=retryable) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise QwenOCRError("OCR_PROVIDER_UNAVAILABLE", retryable=True) from exc
        if status >= 500 or status == 429:
            raise QwenOCRError("OCR_PROVIDER_RETRYABLE", retryable=True)
        if status >= 400:
            raise QwenOCRError("OCR_PROVIDER_REJECTED", retryable=False)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise QwenOCRError("OCR_PROVIDER_INVALID_RESPONSE", retryable=False) from exc
        if not isinstance(payload, Mapping):
            raise QwenOCRError("OCR_PROVIDER_INVALID_RESPONSE", retryable=False)
        text = self._response_text(payload)
        if not text:
            raise QwenOCRError("OCR_EMPTY_RESULT", retryable=False)
        return text
