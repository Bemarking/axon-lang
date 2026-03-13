"""Unit tests for all runtime tool stubs and real implementations."""

from __future__ import annotations

import pytest

from axon.runtime.tools import create_default_registry
from axon.runtime.tools.stubs.api_call_stub import APICallStub
from axon.runtime.tools.stubs.calculator_tool import CalculatorTool
from axon.runtime.tools.stubs.code_executor_stub import CodeExecutorStub
from axon.runtime.tools.stubs.datetime_tool import DateTimeTool
from axon.runtime.tools.stubs.file_reader_stub import FileReaderStub
from axon.runtime.tools.stubs.image_analyzer_stub import ImageAnalyzerStub
from axon.runtime.tools.stubs.pdf_extractor_stub import PDFExtractorStub
from axon.runtime.tools.stubs.web_search_stub import WebSearchStub


# ═════════════════════════════════════════════════════════════════
#  Factory
# ═════════════════════════════════════════════════════════════════


class TestDefaultRegistry:
    def test_all_tools_registered(self) -> None:
        reg = create_default_registry()
        listing = reg.list_tools()
        expected = {
            "WebSearch",
            "CodeExecutor",
            "FileReader",
            "PDFExtractor",
            "ImageAnalyzer",
            "APICall",
            "Calculator",
            "DateTimeTool",
        }
        assert set(listing.keys()) == expected

    def test_stubs_flagged(self) -> None:
        reg = create_default_registry()
        listing = reg.list_tools()
        # Real implementations
        assert listing["Calculator"] is False
        assert listing["DateTimeTool"] is False
        assert listing["CodeExecutor"] is False  # subprocess backend
        # v0.11.0: real backends (may stay stub if deps missing)
        # PDFExtractor and APICall are real if deps are installed
        # Stubs
        for name in ("WebSearch", "ImageAnalyzer"):
            assert listing[name] is True, f"{name} should be a stub"


# ═════════════════════════════════════════════════════════════════
#  WebSearch
# ═════════════════════════════════════════════════════════════════


class TestWebSearchStub:
    @pytest.mark.asyncio
    async def test_returns_results(self) -> None:
        tool = WebSearchStub()
        result = await tool.execute("AXON language", max_results=3)
        assert result.success is True
        assert len(result.data) == 3
        assert "AXON" in result.data[0]["title"]

    @pytest.mark.asyncio
    async def test_max_cap(self) -> None:
        tool = WebSearchStub()
        result = await tool.execute("test", max_results=99)
        assert len(result.data) <= 10

    def test_class_constants(self) -> None:
        assert WebSearchStub.TOOL_NAME == "WebSearch"
        assert WebSearchStub.IS_STUB is True


# ═════════════════════════════════════════════════════════════════
#  CodeExecutor
# ═════════════════════════════════════════════════════════════════


class TestCodeExecutorStub:
    @pytest.mark.asyncio
    async def test_python_sim(self) -> None:
        tool = CodeExecutorStub()
        result = await tool.execute("print(42)", language="python")
        assert result.success is True
        assert result.data["exit_code"] == 0
        assert "Simulated Python" in result.data["stdout"]

    @pytest.mark.asyncio
    async def test_js_sim(self) -> None:
        tool = CodeExecutorStub()
        result = await tool.execute("console.log(1)", language="javascript")
        assert "JS" in result.data["stdout"]


# ═════════════════════════════════════════════════════════════════
#  FileReader
# ═════════════════════════════════════════════════════════════════


class TestFileReaderStub:
    @pytest.mark.asyncio
    async def test_json_extension(self) -> None:
        tool = FileReaderStub()
        result = await tool.execute("data.json")
        assert result.success is True
        assert "application/json" in result.data["mime_type"]

    @pytest.mark.asyncio
    async def test_csv_extension(self) -> None:
        tool = FileReaderStub()
        result = await tool.execute("data.csv")
        assert "text/csv" in result.data["mime_type"]

    @pytest.mark.asyncio
    async def test_plain_text_default(self) -> None:
        tool = FileReaderStub()
        result = await tool.execute("readme.txt")
        assert result.data["mime_type"] == "text/plain"


# ═════════════════════════════════════════════════════════════════
#  PDFExtractor
# ═════════════════════════════════════════════════════════════════


class TestPDFExtractorStub:
    @pytest.mark.asyncio
    async def test_all_pages(self) -> None:
        tool = PDFExtractorStub()
        result = await tool.execute("report.pdf")
        assert result.success is True
        assert result.data["total_pages"] == 3
        assert len(result.data["pages"]) == 3

    @pytest.mark.asyncio
    async def test_page_filter(self) -> None:
        tool = PDFExtractorStub()
        result = await tool.execute("report.pdf", pages=[1, 3])
        assert len(result.data["pages"]) == 2


# ═════════════════════════════════════════════════════════════════
#  ImageAnalyzer
# ═════════════════════════════════════════════════════════════════


class TestImageAnalyzerStub:
    @pytest.mark.asyncio
    async def test_returns_labels(self) -> None:
        tool = ImageAnalyzerStub()
        result = await tool.execute("photo.jpg")
        assert result.success is True
        assert len(result.data["labels"]) == 3
        assert result.data["format"] == "JPEG"

    @pytest.mark.asyncio
    async def test_detail_level_in_metadata(self) -> None:
        tool = ImageAnalyzerStub()
        result = await tool.execute("img.png", detail="high")
        assert result.metadata["detail_level"] == "high"


# ═════════════════════════════════════════════════════════════════
#  APICall
# ═════════════════════════════════════════════════════════════════


class TestAPICallStub:
    @pytest.mark.asyncio
    async def test_get_request(self) -> None:
        tool = APICallStub()
        result = await tool.execute("https://api.example.com/users")
        assert result.success is True
        assert result.data["status_code"] == 200
        assert result.data["body"]["method"] == "GET"

    @pytest.mark.asyncio
    async def test_post_method(self) -> None:
        tool = APICallStub()
        result = await tool.execute("https://api.example.com/data", method="POST")
        assert result.data["body"]["method"] == "POST"


# ═════════════════════════════════════════════════════════════════
#  Calculator (real implementation)
# ═════════════════════════════════════════════════════════════════


class TestCalculatorTool:
    def test_not_stub(self) -> None:
        assert CalculatorTool.IS_STUB is False

    @pytest.mark.asyncio
    async def test_basic_math(self) -> None:
        tool = CalculatorTool()
        result = await tool.execute("2 + 3 * 4")
        assert result.success is True
        assert result.data["result"] == "14"

    @pytest.mark.asyncio
    async def test_invalid_expression(self) -> None:
        tool = CalculatorTool()
        result = await tool.execute("import os")
        assert result.success is False


# ═════════════════════════════════════════════════════════════════
#  DateTimeTool (real implementation)
# ═════════════════════════════════════════════════════════════════


class TestDateTimeTool:
    def test_not_stub(self) -> None:
        assert DateTimeTool.IS_STUB is False

    @pytest.mark.asyncio
    async def test_current_time(self) -> None:
        tool = DateTimeTool()
        result = await tool.execute("now")
        assert result.success is True
        assert "datetime" in result.data or "result" in result.data
