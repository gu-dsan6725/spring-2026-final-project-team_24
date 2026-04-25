class AppError(Exception):
    """Base application error."""

    def __init__(self, detail: str = "An error occurred", status_code: int = 500):
        self.detail = detail
        self.status_code = status_code


class NotFoundError(AppError):
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(detail=detail, status_code=404)


class ForbiddenError(AppError):
    def __init__(self, detail: str = "Forbidden"):
        super().__init__(detail=detail, status_code=403)


class ConflictError(AppError):
    def __init__(self, detail: str = "Conflict"):
        super().__init__(detail=detail, status_code=409)


class CycleError(AppError):
    """Raised when adding a traversal edge would create a cycle in the DAG."""

    def __init__(self, detail: str = "Operation would create a cycle in the traversal DAG"):
        super().__init__(detail=detail, status_code=422)


class PdfExtractError(AppError):
    """Raised when PDF text extraction fails."""

    def __init__(self, detail: str = "PDF extraction failed"):
        super().__init__(detail=detail, status_code=422)


class DocxExtractError(AppError):
    """Raised when DOCX text extraction fails."""

    def __init__(self, detail: str = "DOCX extraction failed"):
        super().__init__(detail=detail, status_code=422)
