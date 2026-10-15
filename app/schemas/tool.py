"""Shared tool error contract."""

class ToolFailure(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
