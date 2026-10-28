"""Uvicorn runner with the historical make_server interface for local scripts."""
import socket
import threading
import uvicorn
from app.config.settings import Settings
from app.main import create_app


class LocalServer:
    def __init__(self, app, port):
        self.app = app
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self._socket.bind(("127.0.0.1", port))
            self._socket.listen(128)
        except BaseException:
            self._socket.close()
            raise
        self.server_port = self._socket.getsockname()[1]
        self._server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.server_port,
            workers=1, log_level="error", access_log=False, ws="none"))
        self._finished = threading.Event()
        self._running = False

    @property
    def db_path(self):
        return self.app.state.settings.db_path

    @property
    def business_date(self):
        return self.app.state.settings.as_of

    def serve_forever(self):
        self._running = True
        try:
            self._server.run(sockets=[self._socket])
        finally:
            self._running = False
            self._finished.set()

    def shutdown(self):
        self._server.should_exit = True
        if self._running:
            self._finished.wait(timeout=15)

    def server_close(self):
        self.shutdown()
        self._socket.close()


def make_server(port=8000, db_path=None, backend="offline", as_of=None, *, require_auth=True, model_settings=None):
    settings = Settings(db_path=str(db_path) if db_path is not None else Settings.db_path,
                        backend=backend, as_of=as_of, require_auth=require_auth)
    return LocalServer(create_app(settings, model_settings=model_settings), port)


def main():
    from app.cli.server import main as run
    return run()


if __name__ == "__main__":
    main()
