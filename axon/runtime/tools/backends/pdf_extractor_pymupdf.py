"""
AXON Runtime — PDFExtractor Backend (v0.11.0, PyMuPDF)
=======================================================
Real PDF text extraction tool replacing ``PDFExtractorStub``.

Uses ``PyMuPDF`` (``import fitz``) for fast, dependency-light
PDF text extraction with page-level control.

Addresses weakness **W9** (PDFExtractor was stub-only).

Dependencies:
    pip install PyMuPDF   # or: pip install axon-lang[tools]
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from axon.runtime.tools.base_tool import BaseTool, ToolResult
from axon.runtime.tools.tool_schema import ToolParameter, ToolSchema


class PDFExtractorPyMuPDF(BaseTool):
    """Real PDF extractor via PyMuPDF (fitz).

    TOOL_NAME matches ``PDFExtractorStub.TOOL_NAME`` so the registry
    can transparently replace the stub.

    Config:
        base_path (str, optional): Directory to resolve relative paths.
        max_pages (int, optional): Maximum pages to extract (default 100).
    """

    TOOL_NAME: ClassVar[str] = "PDFExtractor"
    IS_STUB: ClassVar[bool] = False
    DEFAULT_TIMEOUT: ClassVar[float] = 60.0

    SCHEMA: ClassVar[ToolSchema] = ToolSchema(
        name="PDFExtractor",
        description="Extract text from a PDF file",
        input_params=(
            ToolParameter("query", "str", required=True,
                          description="Path to the PDF file"),
            ToolParameter("pages", "list[int]", required=False,
                          default=None,
                          description="Page numbers to extract (1-indexed)"),
        ),
        output_type="dict",
        timeout_default=60.0,
    )

    def validate_config(self) -> None:
        """Validate optional base_path if provided."""
        base_path = self.config.get("base_path")
        if base_path and not Path(base_path).exists():
            raise ValueError(
                f"base_path does not exist: {base_path}"
            )

    async def execute(self, query: str, **kwargs: Any) -> ToolResult:
        """Extract text from a PDF file.

        Args:
            query:  Path to the PDF file.
            pages:  Optional list of 1-indexed page numbers to extract.

        Returns:
            ToolResult with pages list, total_pages, and filename.
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            return ToolResult(
                success=False,
                data=None,
                error=(
                    "PyMuPDF is required for PDFExtractorPyMuPDF. "
                    "Install with: pip install PyMuPDF"
                ),
            )

        # Resolve path
        file_path = Path(query)
        base_path = self.config.get("base_path")
        if base_path and not file_path.is_absolute():
            file_path = Path(base_path) / file_path

        if not file_path.exists():
            return ToolResult(
                success=False,
                data=None,
                error=f"PDF file not found: {file_path}",
            )

        if file_path.suffix.lower() != ".pdf":
            return ToolResult(
                success=False,
                data=None,
                error=f"Not a PDF file: {file_path.name}",
            )

        page_filter: list[int] | None = kwargs.get("pages")
        max_pages = self.config.get("max_pages", 100)

        try:
            doc = fitz.open(str(file_path))
            total_pages = len(doc)

            pages_data: list[dict[str, Any]] = []

            for page_num in range(total_pages):
                page_1indexed = page_num + 1

                # Apply page filter
                if page_filter and page_1indexed not in page_filter:
                    continue

                # Apply max_pages limit
                if len(pages_data) >= max_pages:
                    break

                page = doc[page_num]
                text = page.get_text("text")

                pages_data.append({
                    "page": page_1indexed,
                    "text": text,
                    "char_count": len(text),
                })

            doc.close()

            return ToolResult(
                success=True,
                data={
                    "pages": pages_data,
                    "total_pages": total_pages,
                    "extracted_pages": len(pages_data),
                    "filename": file_path.name,
                },
                metadata={
                    "is_stub": False,
                    "provider": "pymupdf",
                },
            )

        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                data=None,
                error=f"PDF extraction failed: {exc}",
                metadata={"is_stub": False, "provider": "pymupdf"},
            )
