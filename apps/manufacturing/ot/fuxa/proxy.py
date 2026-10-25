"""Private FUXA tag adapter: fixed endpoint and scoped HMI identity only."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import urllib.error
import urllib.request


def main():
    username, password = os.environ['FUXA_API_USERNAME'], os.environ['FUXA_API_PASSWORD']
    authorization = 'Basic ' + base64.b64encode((username + ':' + password).encode()).decode()
    upstream = os.environ.get('MANUFACTURING_OT_API', 'http://manufacturing-api:8000') + '/api/ot/tags'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def relay(self):
            if self.path != '/tags':
                return self.respond(404, b'{"detail":"Not found"}')
            try:
                body = None
                if self.command == 'POST':
                    length = int(self.headers.get('Content-Length', '-1'))
                    if not 0 < length <= 16384:
                        return self.respond(422, b'{"detail":"Bounded command required"}')
                    body = self.rfile.read(length)
                request = urllib.request.Request(upstream, data=body, headers={
                    'Authorization': authorization, 'Content-Type': 'application/json'})
                with urllib.request.urlopen(request, timeout=10) as reply:
                    return self.respond(reply.status, reply.read())
            except urllib.error.HTTPError as error:
                return self.respond(error.code, error.read())
            except (OSError, ValueError):
                return self.respond(503, b'{"detail":"Manufacturing API unavailable"}')

        def respond(self, status, body):
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = relay
        do_POST = relay

    ThreadingHTTPServer(('0.0.0.0', 8011), Handler).serve_forever()


if __name__ == '__main__':
    main()
