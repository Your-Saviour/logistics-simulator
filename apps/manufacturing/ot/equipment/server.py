"""Private equipment service. The manufacturing controller is its only writer."""
import hmac
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from journal import Engine, Conflict, RecoveryRequired
from modbus import PLC


def main():
    token = os.environ.get('OT_EQUIPMENT_TOKEN', '')
    if len(token) < 16:
        raise ValueError('Explicit OT_EQUIPMENT_TOKEN of at least 16 characters required')
    path = Path(os.environ.get('OT_JOURNAL', '/data/equipment.sqlite'))
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = Engine(str(path), PLC(os.environ.get('PLC_HOST', 'openplc'), int(os.environ.get('PLC_PORT', '502'))))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Never log credentials or command bodies.

        def handle_request(self):
            if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                return self.reply(401, {'detail': 'Equipment authentication required'})
            try:
                if self.command == 'GET' and self.path == '/v1/status':
                    return self.reply(200, engine.status(observe=True))
                if self.command != 'POST' or self.path != '/v1/commands':
                    return self.reply(404, {'detail': 'Not found'})
                size = int(self.headers.get('Content-Length', '-1'))
                if not 0 < size <= 16384:
                    raise ValueError('Bounded JSON body required')
                def invalid_constant(value):
                    raise ValueError('Non-finite JSON number: ' + value)
                body = json.loads(self.rfile.read(size), parse_constant=invalid_constant)
                return self.reply(200, engine.command(body))
            except RecoveryRequired as error:
                return self.reply(409, {'detail': str(error), 'recovery_required': True})
            except Conflict as error:
                return self.reply(409, {'detail': str(error)})
            except (ValueError, KeyError, TypeError) as error:
                return self.reply(422, {'detail': str(error)})
            except OSError:
                return self.reply(503, {'detail': 'PLC unavailable; retry the same command identity'})
            except Exception:
                return self.reply(503, {'detail': 'Equipment journal unavailable; reconciliation may be required'})

        def reply(self, status, value):
            body = json.dumps(value, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = handle_request
        do_POST = handle_request

    server = ThreadingHTTPServer(('0.0.0.0', 8010), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        engine.close()


if __name__ == '__main__':
    main()
