#!/usr/bin/env python3
"""Run BotMonitor: ./venv/bin/python app.py"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import config
from services.monitor import Monitor


def handler_for(monitor):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def send(self, code, body, content_type='application/json; charset=utf-8'):
            encoded = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(encoded)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            host = self.headers.get('Host', '').split(':')[0]
            if host not in ('localhost', '127.0.0.1'):
                return self.send(403, '{"error":"Localhost only"}')
            url = urlsplit(self.path)
            routes = {'/': ('templates/index.html', 'text/html; charset=utf-8'),
                      '/static/app.js': ('static/app.js', 'text/javascript; charset=utf-8'),
                      '/static/explain.js': ('static/explain.js', 'text/javascript; charset=utf-8'),
                      '/static/style.css': ('static/style.css', 'text/css; charset=utf-8')}
            if url.path in routes:
                path, content_type = routes[url.path]
                return self.send(200, (config.ROOT/path).read_bytes(), content_type)
            if url.path == '/api/dashboard':
                data = monitor.get_dashboard()
                return self.send(200 if data else 503, json.dumps(data or {'error':'Initializing'}, allow_nan=False))
            if url.path == '/api/bootstrap.js':
                return self.send(200,'window.BOTMONITOR_INITIAL='+json.dumps(monitor.get_dashboard(),allow_nan=False)+';',
                                 'text/javascript; charset=utf-8')
            if url.path == '/api/history':
                bot = parse_qs(url.query).get('bot', [''])[0]
                if bot not in config.BOTS:
                    return self.send(400, '{"error":"Unknown bot"}')
                return self.send(200, json.dumps(monitor.store.history(bot), allow_nan=False))
            if url.path in ('/api/journal', '/api/inspector', '/api/decisions'):
                params = {k:v[0] for k,v in parse_qs(url.query).items()}
                bot = params.get('bot','')
                if bot not in config.BOTS:
                    return self.send(400, '{"error":"Unknown bot"}')
                if not getattr(monitor, 'explain', None):
                    return self.send(503, '{"error":"Explainability unavailable or disabled; existing monitoring continues"}')
                try:
                    limit = int(params.get('limit', '50'))
                    offset = int(params.get('offset', '0'))
                    if not 1 <= limit <= 200 or not 0 <= offset <= 10000000:
                        raise ValueError()
                    params.update(limit=limit,offset=offset)
                except ValueError:
                    return self.send(400, '{"error":"Invalid pagination"}')
                try:
                    if url.path == '/api/journal':
                        data = monitor.explain.store.journal(bot, params)
                    elif url.path == '/api/decisions':
                        data = monitor.explain.store.events(bot, limit=limit, offset=offset)
                        from services.explain_service import diagnostics
                        data['diagnostics'] = diagnostics(data['items'])
                    else:
                        data = monitor.explain.inspector(bot, params.get('trade',''), limit, offset)
                        if data is None:
                            return self.send(404, '{"error":"Trade not found"}')
                    return self.send(200, json.dumps(data,allow_nan=False))
                except Exception:
                    return self.send(503, '{"error":"Explainability read failed; existing monitoring continues"}')
            if url.path == '/api/health':
                data = monitor.get_dashboard()
                return self.send(200 if data else 503, json.dumps({'ready':bool(data), 'last_refresh':data['timestamp'] if data else None}))
            return self.send(404, '{"error":"Not found"}')

        def do_POST(self):
            self.send(405, '{"error":"Read-only application"}')
        do_PUT = do_PATCH = do_DELETE = do_POST

    return Handler


def main():
    monitor = Monitor()
    if '--check' in sys.argv:
        monitor.refresh_accounts()
        result = monitor.refresh()
        (config.DATA_DIR/'inspection.json').write_text(json.dumps(result,indent=2)+'\n')
        for account in result['accounts']:
            print(account['account'], account.get('error') or 'Account verified', account.get('fill_warning',''))
        for bot in result['bots']:
            print(bot['bot_id'], bot['status'], 'positions=',bot['open_positions'],
                  'today=',bot['trades_today'],'month=',bot['trades_month'],
                  'realized=',bot['realized_pl'],'unrealized=',bot['unrealized_pl'])
        return
    # Bind before collecting anything so an occupied port fails immediately.
    server = ThreadingHTTPServer((config.HOST, config.PORT), handler_for(monitor))
    print(f'BotMonitor: http://{config.HOST}:{config.PORT} (read-only)', flush=True)
    monitor.refresh()
    monitor.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        monitor.stop.set()
        server.server_close()


if __name__ == '__main__':
    main()
