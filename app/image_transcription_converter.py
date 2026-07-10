"""Clean image-to-Markdown transcription via a vision LLM.

markitdown's built-in :class:`ImageConverter` is designed to *describe* an
image: it prepends any EXIF metadata (``ImageSize: …`` etc.) and wraps the
model's answer under a literal ``# Description:`` heading. That's wrong for
OCR — when the user wants the *text in the image* transcribed to Markdown,
the metadata and heading are noise.

This subclass keeps the metadata/description behaviour when no vision model is
configured (identical fallback to the base class) but, when a model is
available, returns *only* the model's transcription so a screenshot or a
document photo becomes clean Markdown.
"""

from __future__ import annotations

from typing import Any, BinaryIO

from markitdown.converters import ImageConverter
from markitdown._base_converter import DocumentConverterResult
from markitdown._stream_info import StreamInfo


class ImageTranscriptionConverter(ImageConverter):
    """Return only the vision model's transcription — no EXIF block, no
    ``# Description:`` heading."""

    def convert(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,
    ) -> DocumentConverterResult:
        llm_client = kwargs.get("llm_client")
        llm_model = kwargs.get("llm_model")

        # No vision model wired up → behave exactly like the base converter
        # (metadata only). This keeps OCR-off / misconfigured runs unsurprising.
        if llm_client is None or llm_model is None:
            return super().convert(file_stream, stream_info, **kwargs)

        transcription = self._get_llm_description(
            file_stream,
            stream_info,
            client=llm_client,
            model=llm_model,
            prompt=kwargs.get("llm_prompt"),
        )
        return DocumentConverterResult(
            markdown=((transcription or "").strip() + "\n"),
        )
