"""Cobertura das otimizações Tier 1 do token-optimization-plan.

Testa:
- Compressão de imagem antes do base64 (Tier 1.2)
- Roteamento por complexidade (Tier 1.3)
- Log de usage com cache metrics (Tier 1.1)
- Default de max_semantic_retries=1 (Tier 1.4)
"""

from __future__ import annotations

import base64
import io
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from app.integrations.anthropic.client import (
    _HAIKU_TEXT_MAX_CHARS,
    _IMAGE_MAX_SIDE,
    AnthropicClient,
    _compress_image,
)

pytestmark = pytest.mark.asyncio


def _big_png_bytes(size=(2500, 1800)) -> bytes:
    img = Image.new("RGB", size, color=(200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _small_png_bytes(size=(200, 150)) -> bytes:
    img = Image.new("RGB", size, color=(50, 100, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Compressão de imagem (Tier 1.2)
# ---------------------------------------------------------------------------


def test_compress_resizes_and_reencodes_as_jpeg():
    """Imagem grande PNG → redimensionada para ≤ 1024 + JPEG."""
    original = _big_png_bytes()
    compressed, media_type = _compress_image(original, "image/png")
    assert media_type == "image/jpeg"
    with Image.open(io.BytesIO(compressed)) as img:
        assert max(img.size) <= _IMAGE_MAX_SIDE
    # Compressão real: JPEG q=75 de imagem grande é dramaticamente menor.
    assert len(compressed) < len(original) / 3


def test_compress_small_png_still_converts_to_jpeg():
    """PNG pequeno não redimensiona mas ainda vira JPEG (menor overhead)."""
    original = _small_png_bytes()
    compressed, media_type = _compress_image(original, "image/png")
    assert media_type == "image/jpeg"


def test_compress_small_jpeg_untouched():
    """JPEG já pequeno é passado direto — sem re-encoding desnecessário."""
    img = Image.new("RGB", (300, 200), color=(0, 255, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    original = buf.getvalue()
    compressed, media_type = _compress_image(original, "image/jpeg")
    assert media_type == "image/jpeg"
    assert compressed == original


def test_compress_invalid_bytes_returns_original():
    """Bytes que não são imagem → passa original (best-effort)."""
    data = b"not an image at all"
    compressed, media_type = _compress_image(data, "image/png")
    assert compressed == data
    assert media_type == "image/png"


def test_build_user_content_compresses_images_in_base64():
    """A cadeia completa: bytes → compress → base64 no payload."""
    original = _big_png_bytes()
    content = AnthropicClient._build_user_content(
        "descreva a imagem", [("image/png", original)]
    )
    image_block = next(b for b in content if b["type"] == "image")
    assert image_block["source"]["media_type"] == "image/jpeg"
    decoded = base64.b64decode(image_block["source"]["data"])
    assert len(decoded) < len(original) / 3


# ---------------------------------------------------------------------------
# Roteamento por complexidade (Tier 1.3)
# ---------------------------------------------------------------------------


def _client(model="sonnet", fallback="haiku") -> AnthropicClient:
    c = AnthropicClient(
        api_key="test-key",
        model=model,
        fallback_model=fallback,
    )
    return c


def test_router_picks_fallback_for_text_only_short():
    c = _client()
    assert c._pick_model(has_images=False, user_text="500 ml de água") == "haiku"


def test_router_picks_primary_for_images():
    c = _client()
    assert c._pick_model(has_images=True, user_text=None) == "sonnet"
    assert (
        c._pick_model(has_images=True, user_text="rótulo desse iogurte") == "sonnet"
    )


def test_router_picks_primary_for_long_text():
    c = _client()
    long_text = "x" * (_HAIKU_TEXT_MAX_CHARS + 1)
    assert c._pick_model(has_images=False, user_text=long_text) == "sonnet"


def test_router_picks_fallback_for_empty_user_text():
    c = _client()
    assert c._pick_model(has_images=False, user_text=None) == "haiku"


def test_router_no_fallback_configured_falls_back_to_primary():
    """Se `fallback_model` não for configurado, cai no primário."""
    c = AnthropicClient(api_key="test-key", model="sonnet")
    assert c._pick_model(has_images=False, user_text="curto") == "sonnet"


# ---------------------------------------------------------------------------
# Log de usage com cache metrics (Tier 1.1)
# ---------------------------------------------------------------------------


async def test_call_logs_cache_metrics(caplog: pytest.LogCaptureFixture):
    """Após a chamada, um log estruturado deve conter os campos de cache."""
    c = _client()
    fake_response = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                name="record_intent",
                input={
                    "intent": "clarify",
                    "confidence": 0.5,
                    "user_text_summary": ".",
                    "needs_clarification": True,
                    "clarification_question": "?",
                },
            )
        ],
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=30,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=90,
        ),
    )
    c._client = SimpleNamespace(  # type: ignore[assignment]
        messages=SimpleNamespace(create=AsyncMock(return_value=fake_response))
    )

    with caplog.at_level(logging.INFO, logger="app.anthropic"):
        result = await c.call_record_intent(user_text="oi")

    assert result.error is None
    usage_records = [
        r for r in caplog.records if getattr(r, "event", None) == "anthropic_usage"
    ]
    assert len(usage_records) == 1
    r = usage_records[0]
    assert r.cache_read_input_tokens == 90
    assert r.cache_creation_input_tokens == 0
    assert r.input_tokens == 100
    assert r.output_tokens == 30
    assert r.model == "haiku"  # roteamento: texto curto sem foto


# ---------------------------------------------------------------------------
# Default de retries semânticos (Tier 1.4)
# ---------------------------------------------------------------------------


async def test_default_max_semantic_retries_is_1():
    """Antes eram 2 retries. Agora 1 — economiza tokens no pior caso."""
    from inspect import signature

    sig = signature(AnthropicClient.call_record_intent)
    assert sig.parameters["max_semantic_retries"].default == 1
