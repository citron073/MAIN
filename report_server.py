# report_server.py
import json
import subprocess
import sys
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent

def run_daily_report_json(arg_file=None):
    cmd = [sys.executable, str(HERE / "daily_report.py")]
    if arg_file:
        cmd.append(str(arg_file))
    cmd.append("--json")

    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        return None, {"error": "daily_report_failed", "stderr": p.stderr[-4000:], "cmd": cmd}

    # stdout の [JSON_OUTPUT] 以降を探す
    marker = "[JSON_OUTPUT]"
    idx = p.stdout.find(marker)
    if idx < 0:
        return None, {"error": "json_marker_not_found", "stdout_tail": p.stdout[-2000:], "cmd": cmd}

    s = p.stdout[idx + len(marker):].strip()
    try:
        return json.loads(s), None
    except Exception:
        return None, {"error": "json_parse_failed", "json_tail": s[-2000:], "cmd": cmd}

def pick_latest_trade_log():
    logs = (HERE / "../logs").resolve()
    if not logs.exists():
        logs = (HERE / "logs").resolve()
    files = sorted(list(logs.glob("trade_log_*.csv")))
    return files[-1] if files else None

class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, status=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)

        if u.path == "/api/latest":
            f = pick_latest_trade_log()
            if not f:
                return self._send_json({"error": "no_trade_log_found"}, 404)

            data, err = run_daily_report_json(f)
            if err:
                return self._send_json(err, 500)
            return self._send_json(data, 200)

        if u.path == "/api/report":
            files = qs.get("file", [])
            if not files:
                return self._send_json({"error": "file_param_required"}, 400)

            f = Path(files[0])
            # 相対指定なら ../logs 配下を想定
            if not f.is_absolute():
                cand1 = (HERE / "../logs" / f.name).resolve()
                cand2 = (HERE / "logs" / f.name).resolve()
                if cand1.exists():
                    f = cand1
                elif cand2.exists():
                    f = cand2

            if not f.exists():
                return self._send_json({"error": "file_not_found", "file": str(f)}, 404)

            data, err = run_daily_report_json(f)
            if err:
                return self._send_json(err, 500)
            return self._send_json(data, 200)

        if u.path == "/":
            return self._send_json({
                "ok": True,
                "endpoints": ["/api/latest", "/api/report?file=trade_log_YYYYMMDD.csv"]
            }, 200)

        return self._send_json({"error": "not_found"}, 404)

def main():
    host = "127.0.0.1"
    port = 8811
    httpd = HTTPServer((host, port), Handler)
    print(f"report_server: http://{host}:{port}")
    httpd.serve_forever()

if __name__ == "__main__":
    main()
