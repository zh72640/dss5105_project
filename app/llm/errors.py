"""Shared model backend failure contract."""


class BackendError(RuntimeError):
    def __init__(self, code, retryable=True):
        super().__init__(code)
        self.retryable = retryable
