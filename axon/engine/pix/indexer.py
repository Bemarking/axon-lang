"""
AXON Engine — PIX Indexer
============================
Document-to-tree indexation: transforms source documents (Markdown, PDF)
into a PIX DocumentTree for navigational retrieval.

Architecture:
  StructureExtractor (protocol) → PixIndexer → DocumentTree

  The StructureExtractor defines how to detect headings and sections
  in a specific document format. The PixIndexer orchestrates tree
  construction using recursive summarization.

Included extractors:
  - MarkdownExtractor: Heading-based structure from Markdown files.
  - (Future) PdfExtractor: Layout-based structure from PDF documents.

Computational complexity:
  O(n · log(n) · C_LLM) for indexation
  where n = document sections, C_LLM = cost per summarization
"""

from __future__ import annotations

import re
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from axon.engine.pix.document_tree import DocumentTree, PixNode, PixLocation


@dataclass
class Section:
    """A detected document section with its content and metadata."""

    title: str
    content: str
    level: int  # heading level (1 = h1, 2 = h2, etc.)
    start_offset: int = 0
    end_offset: int = 0
    subsections: list[Section] = field(default_factory=list)

    @property
    def full_content(self) -> str:
        """Content including all subsection content."""
        parts = [self.content]
        for sub in self.subsections:
            parts.append(sub.full_content)
        return "\n".join(parts)


@runtime_checkable
class StructureExtractor(Protocol):
    """Protocol for document structure detection.

    Implementations detect section boundaries from document content
    and return a hierarchical list of Section objects.
    """

    def extract(self, content: str) -> list[Section]:
        """Extract hierarchical sections from document content.

        Args:
            content: Raw document text.

        Returns:
            List of top-level Section objects (with nested subsections).
        """
        ...


@runtime_checkable
class SummarizationFunction(Protocol):
    """Protocol for content summarization.

    Implementations compress content into a navigational summary:
    CR(nᵢ) = H(summaryᵢ) / H(contentᵢ) ∈ [0.05, 0.15]
    """

    def summarize(self, content: str, max_words: int = 50) -> str:
        """Produce a navigational summary of the content.

        Args:
            content:   Full section content.
            max_words: Maximum words in the summary.

        Returns:
            Compressed summary preserving navigational salience.
        """
        ...


class TruncationSummarizer:
    """Simple truncation-based summarizer for testing.

    Takes the first N words of the content. Not intended for
    production — use an LLM-based summarizer instead.
    """

    def summarize(self, content: str, max_words: int = 50) -> str:
        words = content.split()
        if len(words) <= max_words:
            return content.strip()
        return " ".join(words[:max_words]) + "..."


class MarkdownExtractor:
    """Extract hierarchical structure from Markdown documents.

    Detects headings (# to ######) and builds a nested section tree.
    Content between headings is assigned to the preceding heading.
    """

    _HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    def extract(self, content: str) -> list[Section]:
        """Extract sections from Markdown content."""
        headings: list[tuple[int, str, int]] = []
        for match in self._HEADING_RE.finditer(content):
            level = len(match.group(1))
            title = match.group(2).strip()
            start = match.start()
            headings.append((level, title, start))

        if not headings:
            # No headings → treat entire document as one section
            return [
                Section(
                    title="Document",
                    content=content.strip(),
                    level=1,
                    start_offset=0,
                    end_offset=len(content),
                )
            ]

        # Build sections with content between headings
        sections: list[Section] = []
        for i, (level, title, start) in enumerate(headings):
            end = headings[i + 1][2] if i + 1 < len(headings) else len(content)
            # Content is everything after the heading line until next heading
            heading_line_end = content.index("\n", start) + 1 if "\n" in content[start:] else len(content)
            section_content = content[heading_line_end:end].strip()
            sections.append(
                Section(
                    title=title,
                    content=section_content,
                    level=level,
                    start_offset=start,
                    end_offset=end,
                )
            )

        # Build hierarchy: nest sections under their parent headings
        return self._build_hierarchy(sections)

    def _build_hierarchy(self, sections: list[Section]) -> list[Section]:
        """Nest sections into a hierarchy based on heading levels."""
        if not sections:
            return []

        result: list[Section] = []
        stack: list[Section] = []

        for section in sections:
            # Pop sections from stack that are at same or deeper level
            while stack and stack[-1].level >= section.level:
                stack.pop()

            if stack:
                # This section is a child of the top-of-stack
                stack[-1].subsections.append(section)
            else:
                # This is a top-level section
                result.append(section)

            stack.append(section)

        return result


class PixIndexer:
    """Orchestrates tree construction from documents.

    Takes a document, extracts its structure using a StructureExtractor,
    then builds a DocumentTree with compressed summaries at each node.

    Example:
        extractor = MarkdownExtractor()
        summarizer = MyLLMSummarizer()
        indexer = PixIndexer(extractor, summarizer, max_depth=4)

        tree = indexer.index(
            content=open("contract.md").read(),
            name="contract_v2",
            source="contract.md"
        )
    """

    def __init__(
        self,
        extractor: StructureExtractor,
        summarizer: SummarizationFunction | None = None,
        max_depth: int = 6,
    ) -> None:
        self._extractor = extractor
        self._summarizer = summarizer or TruncationSummarizer()
        self._max_depth = max_depth
        self._node_counter = 0

    def index(
        self,
        content: str,
        name: str = "document",
        source: str = "",
    ) -> DocumentTree:
        """Index a document into a PIX DocumentTree.

        Args:
            content: Raw document text.
            name:    Name for the document tree.
            source:  Source file path or URL.

        Returns:
            A fully constructed DocumentTree.
        """
        self._node_counter = 0

        # Extract structure
        sections = self._extractor.extract(content)

        # Build root node
        root_summary = self._summarizer.summarize(content[:500])
        root = PixNode(
            node_id=self._next_id(),
            title=name,
            summary=root_summary,
            location=PixLocation(
                page_start=0,
                page_end=0,
                offset_start=0,
                offset_end=len(content),
            ),
            depth=0,
        )

        # Build child nodes recursively
        for section in sections:
            child = self._build_node(section, depth=1)
            root.add_child(child)

        return DocumentTree(name=name, root=root, source=source)

    def _build_node(self, section: Section, depth: int) -> PixNode:
        """Recursively build a PixNode from a Section."""
        node_id = self._next_id()

        # Summarize the section's own content
        summary = self._summarizer.summarize(section.content) if section.content else ""

        node = PixNode(
            node_id=node_id,
            title=section.title,
            summary=summary,
            location=PixLocation(
                offset_start=section.start_offset,
                offset_end=section.end_offset,
            ),
            depth=depth,
        )

        if section.subsections and depth < self._max_depth:
            # Internal node: recurse into subsections
            for sub in section.subsections:
                child = self._build_node(sub, depth + 1)
                node.add_child(child)
        else:
            # Leaf node: store full content
            node.content = section.full_content

        return node

    def _next_id(self) -> str:
        """Generate a unique node ID."""
        self._node_counter += 1
        return f"pix_{self._node_counter:04d}"
