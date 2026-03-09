"""
Async PDF ingestion: fetch -> parse -> validate.

Extracts text from sample_merchant_summary.pdf asynchronously.
In production, this would be a proper background job (e.g. Celery task,
message queue consumer, or async worker) rather than an inline async call,
since PDF processing can be slow for large documents.

The PDF uses an unusual layout where multiple lines are overlaid at the
same y-position. We reconstruct the text by detecting x-position resets
(when the cursor jumps back to the left, it indicates a new line).
"""

import asyncio
import logging
from pathlib import Path

import pdfplumber
from pydantic import ValidationError

from ingestion.validators import PDFSummary

logger = logging.getLogger(__name__)

DEFAULT_PDF_PATH = Path("data/sample_merchant_summary.pdf")


def _extract_text_from_pdf(file_path: Path) -> str:
    """
    Fetch + Parse: Read the PDF and extract text.

    This is a blocking (synchronous) operation because pdfplumber
    does not support async. We wrap it with asyncio.to_thread()
    in the async entry point below.

    The PDF has all characters at the same y-position but with
    x-position resets between logical lines, so we split on those.
    """
    logger.info(f"Extracting text from PDF: {file_path}")

    with pdfplumber.open(file_path) as pdf:
        all_lines = []

        for page in pdf.pages:
            chars = page.chars
            if not chars:
                continue

            # Detect line breaks by finding where x-position resets
            # (jumps back to the left), indicating a new logical line
            x_positions = [c["x0"] for c in chars]
            line_start = 0

            for i in range(1, len(x_positions)):
                if x_positions[i] < x_positions[i - 1] - 5:
                    line_text = "".join(c["text"] for c in chars[line_start:i])
                    all_lines.append(line_text.strip())
                    line_start = i

            # Don't forget the last line
            last_line = "".join(c["text"] for c in chars[line_start:])
            all_lines.append(last_line.strip())

    text = "\n".join(all_lines)
    logger.info(f"Extracted {len(all_lines)} lines ({len(text)} chars) from PDF")
    return text


def validate_pdf_summary(raw_text: str, file_path: Path) -> PDFSummary | None:
    """
    Validate: Run extracted data through our Pydantic model.
    """
    try:
        return PDFSummary(source_file=str(file_path), raw_text=raw_text)
    except ValidationError as e:
        logger.warning(f"PDF validation failed: {e}")
        return None


async def ingest_pdf(file_path: Path = DEFAULT_PDF_PATH) -> PDFSummary | None:
    """
    Main async entry point: extract text from PDF asynchronously.

    asyncio.to_thread() runs the blocking pdfplumber call in a
    separate thread so it doesn't block the async event loop.
    In production, this entire function would be a background job
    (e.g. Celery task or message queue consumer).
    """
    if not file_path.exists():
        logger.error(f"PDF file not found: {file_path}")
        return None

    # Run blocking PDF extraction in a thread pool
    raw_text = await asyncio.to_thread(_extract_text_from_pdf, file_path)

    if not raw_text:
        logger.warning("No text extracted from PDF")
        return None

    return validate_pdf_summary(raw_text, file_path)
