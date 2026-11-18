"""Локальный просмотрщик. Запуск из корня: python src/review_app.py."""
from __future__ import annotations
import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import webbrowser


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    ui = Path(__file__).resolve().parent / 'review_ui'
    if not (ui / 'review.html').exists():
        parser.error('Нет src/review_ui/review.html. Скопируйте review_ui рядом с review_app.py.')
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(ui))
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
    except OSError as exc:
        parser.exit(1, f'Порт {args.port} недоступен: {exc}\nПопробуйте --port 8766.\n')
    url = f'http://127.0.0.1:{args.port}/review.html'
    print(f'Откройте Chrome или Edge: {url}\nОстановка: Ctrl+C.')
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
