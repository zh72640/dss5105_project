"""Start the server; lifespan loads environment configuration and resources."""
import argparse
from datetime import date

from app.main import create_app


def main():
    from app.server import LocalServer
    parser = argparse.ArgumentParser(description="SweaterCo FastAPI server (single process, SQLite)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", help="Override DISPATCH_DB.")
    parser.add_argument("--backend", choices=["offline", "llm", "deepseek"], help="Legacy backend selection.")
    parser.add_argument("--mode", choices=["offline", "llm"], help="Default mode (LLM unless configured otherwise).")
    parser.add_argument("--model-key", help="Default configured model alias.")
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--no-auth", action="store_true", default=None,
                        help="Local demonstration mode; actor is local-demo.")
    args = parser.parse_args()
    overrides = {"db_path": args.db, "backend": args.backend, "mode": args.mode,
                 "model_key": args.model_key, "as_of": args.as_of,
                 "require_auth": False if args.no_auth else None}
    try:
        server = LocalServer(create_app(config_overrides=overrides), args.port)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(f"Starting SweaterCo | http://127.0.0.1:{server.server_port} | API docs /docs", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
