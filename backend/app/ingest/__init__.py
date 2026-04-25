"""Document ingestion — extract and chunk content from uploaded files.

Primary extractor: MinerU (``pip install mineru``), called via
``app.services.extraction_service``. Handles PDF, images, DOCX with
table/formula/image extraction → markdown output.

Supporting utilities:
- ``chunker`` — split extracted text into concept-sized sections
- ``sanitize`` — strip DB-unsafe characters
- ``html`` — BeautifulSoup visible text extraction
- ``docx`` — python-docx fallback for simple DOCX
"""
