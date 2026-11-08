"""Receptor de notificaciones de Alertmanager (webhook). Sustituye a un canal real (correo/Teams/Telegram) en la demo:
guarda cada notificacion y la muestra en una pagina para verla en tiempo real."""
import html
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

ARCHIVO = os.getenv("ALERTAS_PATH", "/estado/alertas_recibidas.jsonl")


def leer():
    try:
        with open(ARCHIVO, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    except OSError:
        return []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        cuerpo = json.loads(self.rfile.read(n) or b"{}")
        os.makedirs(os.path.dirname(ARCHIVO), exist_ok=True)
        with open(ARCHIVO, "a", encoding="utf-8") as f:
            for a in cuerpo.get("alerts", []):
                f.write(json.dumps({"recibida": time.strftime("%H:%M:%S"), "estado": a["status"],
                                    "alerta": a["labels"].get("alertname"), "severidad": a["labels"].get("severity"),
                                    "resumen": a["annotations"].get("summary", ""),
                                    "runbook": a["annotations"].get("runbook", "")}, ensure_ascii=False) + "\n")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self):
        filas = ""
        for a in reversed(leer()[-40:]):
            color = "#c0392b" if a["estado"] == "firing" else "#1e8449"
            filas += (f"<tr><td>{a['recibida']}</td><td style='color:{color};font-weight:700'>{a['estado'].upper()}</td>"
                      f"<td>{html.escape(a['alerta'] or '')}</td><td>{html.escape(a['severidad'] or '')}</td>"
                      f"<td>{html.escape(a['resumen'])}</td><td>{html.escape(a['runbook'])}</td></tr>")
        pagina = ("<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=5><title>Receptor de alertas</title>"
                  "<style>body{font-family:Segoe UI,Arial;margin:24px;background:#f6f8fa;color:#1f2937}"
                  "table{border-collapse:collapse;width:100%;background:#fff}th,td{border:1px solid #d0d7de;padding:6px 10px;"
                  "font-size:14px;text-align:left}th{background:#1f3a5f;color:#fff}</style>"
                  "<h2>Receptor de notificaciones (webhook de Alertmanager)</h2>"
                  "<p>Canal simulado: cada fila es una notificacion que recibiria el equipo.</p>"
                  "<table><tr><th>Hora</th><th>Estado</th><th>Alerta</th><th>Severidad</th><th>Resumen</th><th>Runbook</th></tr>"
                  f"{filas}</table>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(pagina.encode())


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 9099), H).serve_forever()
