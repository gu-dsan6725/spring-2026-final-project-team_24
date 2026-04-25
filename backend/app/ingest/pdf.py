"""PDF extraction — delegates to MinerU (pip install mineru).

For direct use, call the extraction service::

    from app.services.extraction_service import extract_file
    extract_file("data/some.pdf")  # writes .md + images to data/extracted/
"""
