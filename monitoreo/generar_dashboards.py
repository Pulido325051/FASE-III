"""Genera los dashboards de Grafana (JSON) que se cargan solos al arrancar.  Uso:  python generar_dashboards.py"""
import json
import os

SALIDA = os.path.join(os.path.dirname(__file__), "grafana", "dashboards")
DS = {"type": "prometheus", "uid": "prom"}
_id = [0]


def _pos(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def _t(exprs):
    return [{"refId": chr(65 + i), "expr": e, "legendFormat": l, "datasource": DS} for i, (e, l) in enumerate(exprs)]


def stat(titulo, expr, pos, unidad="short", umbrales=None, desc="", decimales=None, mapa=None):
    _id[0] += 1
    pasos = umbrales or [{"color": "green", "value": None}]
    campo = {"unit": unidad, "thresholds": {"mode": "absolute", "steps": pasos}, "mappings": mapa or []}
    if decimales is not None:
        campo["decimals"] = decimales
    return {"id": _id[0], "type": "stat", "title": titulo, "description": desc, "datasource": DS, "gridPos": pos,
            "targets": _t([(expr, "")]), "fieldConfig": {"defaults": campo, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background", "graphMode": "area", "textMode": "value"}}


def serie(titulo, exprs, pos, unidad="short", desc="", umbrales=None, apilado=False, minimo=None, maximo=None):
    _id[0] += 1
    campo = {"unit": unidad, "custom": {"lineWidth": 2, "fillOpacity": 18 if apilado else 8, "showPoints": "never",
                                         "stacking": {"mode": "normal" if apilado else "none"}}}
    if minimo is not None:
        campo["min"] = minimo
    if maximo is not None:
        campo["max"] = maximo
    if umbrales:
        campo["thresholds"] = {"mode": "absolute", "steps": umbrales}
        campo["custom"]["thresholdsStyle"] = {"mode": "line"}
    return {"id": _id[0], "type": "timeseries", "title": titulo, "description": desc, "datasource": DS, "gridPos": pos,
            "targets": _t(exprs), "fieldConfig": {"defaults": campo, "overrides": []},
            "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}}


def tabla(titulo, expr, pos, desc=""):
    _id[0] += 1
    return {"id": _id[0], "type": "table", "title": titulo, "description": desc, "datasource": DS, "gridPos": pos,
            "targets": [{"refId": "A", "expr": expr, "format": "table", "instant": True, "datasource": DS}],
            "transformations": [{"id": "organize", "options": {"excludeByName": {"Time": True, "__name__": True, "Value": True, "job": True, "instance": True, "alertstate": True}}}],
            "options": {"showHeader": True}}


def tablero(uid, titulo, paneles, desc):
    return {"uid": uid, "title": titulo, "description": desc, "tags": ["expedientes"], "timezone": "browser",
            "schemaVersion": 39, "version": 1, "refresh": "5s", "time": {"from": "now-15m", "to": "now"},
            "panels": paneles, "templating": {"list": []}, "annotations": {"list": []}}


VERDE_ROJO = [{"color": "green", "value": None}, {"color": "red", "value": 1}]
LAT = "histogram_quantile(%s, sum by (le) (rate(expedientes_http_request_duration_seconds_bucket{ruta=\"/clasificar\"}[1m])))"
ERR = '(sum(rate(expedientes_http_requests_total{codigo=~"5.."}[2m])) or vector(0)) / clamp_min(sum(rate(expedientes_http_requests_total[2m])), 0.001)'


def d1():
    p = [
        stat("API disponible", 'up{job="api"}', _pos(0, 0, 4, 4), umbrales=[{"color": "red", "value": None}, {"color": "green", "value": 1}],
             mapa=[{"type": "value", "options": {"0": {"text": "CAIDA"}, "1": {"text": "EN LINEA"}}}], desc="1 = el scrape de /metrics responde"),
        stat("Peticiones / s", "sum(rate(expedientes_http_requests_total[1m]))", _pos(4, 0, 4, 4), "reqps", decimales=2),
        stat("Errores 5xx (2 min)", ERR, _pos(8, 0, 4, 4), "percentunit", decimales=1,
             umbrales=[{"color": "green", "value": None}, {"color": "orange", "value": 0.01}, {"color": "red", "value": 0.05}]),
        stat("p95 de /clasificar", LAT % "0.95", _pos(12, 0, 4, 4), "s", decimales=1,
             umbrales=[{"color": "green", "value": None}, {"color": "orange", "value": 10}, {"color": "red", "value": 15}],
             desc="Objetivo del SLO (demo): menos de 15 s"),
        stat("Lecturas en proceso", "expedientes_clasificar_en_curso", _pos(16, 0, 4, 4)),
        stat("Alertas activas", 'count(ALERTS{alertstate="firing"}) or vector(0)', _pos(20, 0, 4, 4),
             umbrales=[{"color": "green", "value": None}, {"color": "red", "value": 1}]),
        serie("Peticiones por codigo HTTP", [('sum by (codigo) (rate(expedientes_http_requests_total[1m]))', "{{codigo}}")], _pos(0, 4, 12, 8), "reqps", apilado=True),
        serie("Latencia de /clasificar (p50 / p95)", [(LAT % "0.5", "p50"), (LAT % "0.95", "p95")], _pos(12, 4, 12, 8), "s",
              umbrales=[{"color": "transparent", "value": None}, {"color": "red", "value": 15}], desc="Linea roja = limite del SLO (demo)"),
        serie("Duracion media por etapa (traza)", [('sum by (etapa) (rate(expedientes_etapa_duracion_seconds_sum[1m])) / sum by (etapa) (rate(expedientes_etapa_duracion_seconds_count[1m]))', "{{etapa}}")],
              _pos(0, 12, 12, 8), "s", desc="Cada etapa del procesamiento es un span de la traza de la peticion"),
        serie("CPU y memoria de la API", [("rate(process_cpu_seconds_total{job=\"api\"}[1m])", "CPU (nucleos)"), ("process_resident_memory_bytes{job=\"api\"} / 1024 / 1024 / 1024", "Memoria (GiB)")],
              _pos(12, 12, 12, 8)),
    ]
    return tablero("expedientes-servicio", "D1 - Salud del servicio", p, "Indicadores de servicio: disponibilidad, errores, latencia y recursos")


def d2():
    p = [
        stat("Documentos clasificados", "sum(expedientes_prediccion_total)", _pos(0, 0, 4, 4)),
        stat("Margen mediano (ult. 5 min)", "histogram_quantile(0.5, sum by (le) (rate(expedientes_margen_decision_bucket[5m])))", _pos(4, 0, 4, 4),
             decimales=2, desc="Linea base del modelo: 2.05"),
        stat("Baja confianza", "sum(rate(expedientes_baja_confianza_total[5m])) / clamp_min(sum(rate(expedientes_prediccion_total[5m])), 0.0001)", _pos(8, 0, 4, 4),
             "percentunit", decimales=1, umbrales=[{"color": "green", "value": None}, {"color": "orange", "value": 0.1}, {"color": "red", "value": 0.25}], desc="Linea base ~3 %"),
        stat("CURP verificada", "sum(rate(expedientes_curp_verificada_total[5m])) / clamp_min(sum(rate(expedientes_prediccion_total[5m])), 0.0001)", _pos(12, 0, 4, 4),
             "percentunit", decimales=0, umbrales=[{"color": "red", "value": None}, {"color": "orange", "value": 0.6}, {"color": "green", "value": 0.8}]),
        stat("Correcciones de categoria", "sum(expedientes_correccion_categoria_total) or vector(0)", _pos(16, 0, 4, 4)),
        tabla("Modelo en produccion", "expedientes_modelo_info", _pos(20, 0, 4, 4)),
        serie("Documentos por clase predicha (por minuto)", [("sum by (clase) (rate(expedientes_prediccion_total[1m])) * 60", "{{clase}}")], _pos(0, 4, 12, 8), apilado=True),
        serie("Margen de decision (p10 / p50 / p90)",
              [("histogram_quantile(%s, sum by (le) (rate(expedientes_margen_decision_bucket[1m])))" % q, "p" + str(int(float(q) * 100))) for q in ("0.1", "0.5", "0.9")],
              _pos(12, 4, 12, 8), umbrales=[{"color": "transparent", "value": None}, {"color": "orange", "value": 1.2}],
              desc="Por debajo de 1.2 el documento se marca como duda (revision humana)"),
        serie("Lectura de datos (tasa de exito)",
              [("sum(rate(expedientes_curp_verificada_total[2m])) / clamp_min(sum(rate(expedientes_prediccion_total[2m])), 0.0001)", "CURP verificada"),
               ("sum(rate(expedientes_nombre_encontrado_total[2m])) / clamp_min(sum(rate(expedientes_prediccion_total[2m])), 0.0001)", "Nombre"),
               ("sum(rate(expedientes_fecha_encontrada_total[2m])) / clamp_min(sum(rate(expedientes_prediccion_total[2m])), 0.0001)", "Fecha de nacimiento")],
              _pos(0, 12, 12, 8), "percentunit", minimo=0, maximo=1),
        serie("Correcciones humanas y retractaciones", [("sum(increase(expedientes_correccion_categoria_total[2m]))", "Cambios de categoria (2 min)"),
                                                          ("sum(increase(expedientes_retractacion_total[2m]))", "Reemplazos (2 min)"),
                                                          ("sum(increase(expedientes_eliminado_total[2m]))", "Eliminados (2 min)")], _pos(12, 12, 12, 8)),
    ]
    return tablero("expedientes-modelo", "D2 - Desempeno del modelo", p, "Calidad percibida del modelo sin necesitar etiquetas reales")


def d3():
    p = [
        stat("PSI margen", 'expedientes_monitor_psi{senal="margen"}', _pos(0, 0, 4, 4), decimales=3, umbrales=[{"color": "green", "value": None}, {"color": "orange", "value": 0.1}, {"color": "red", "value": 0.25}]),
        stat("PSI palabras por documento", 'expedientes_monitor_psi{senal="palabras"}', _pos(4, 0, 4, 4), decimales=3, umbrales=[{"color": "green", "value": None}, {"color": "orange", "value": 0.1}, {"color": "red", "value": 0.25}]),
        stat("PSI cobertura de vocabulario", 'expedientes_monitor_psi{senal="cobertura"}', _pos(8, 0, 4, 4), decimales=3, umbrales=[{"color": "green", "value": None}, {"color": "orange", "value": 0.1}, {"color": "red", "value": 0.25}]),
        stat("PSI mezcla de clases", 'expedientes_monitor_psi{senal="clase"}', _pos(12, 0, 4, 4), decimales=3, umbrales=[{"color": "green", "value": None}, {"color": "orange", "value": 0.1}, {"color": "red", "value": 0.25}]),
        stat("Documentos en la ventana", "expedientes_monitor_ventana_documentos", _pos(16, 0, 4, 4)),
        stat("Documentos de referencia", "expedientes_monitor_referencia_documentos", _pos(20, 0, 4, 4)),
        serie("PSI por senal (0,1 = atencion, 0,25 = deriva)", [("expedientes_monitor_psi", "{{senal}}")], _pos(0, 4, 14, 9),
              umbrales=[{"color": "transparent", "value": None}, {"color": "orange", "value": 0.1}, {"color": "red", "value": 0.25}], minimo=0),
        serie("Indicadores en la ventana", [("expedientes_monitor_tasa", "{{indicador}}")], _pos(14, 4, 10, 9), "percentunit", minimo=0, maximo=1),
        serie("Palabras de texto por documento (p10 / p50 / p90)",
              [("histogram_quantile(%s, sum by (le) (rate(expedientes_texto_palabras_bucket[2m])))" % q, "p" + str(int(float(q) * 100))) for q in ("0.1", "0.5", "0.9")], _pos(0, 13, 12, 8)),
        serie("Cobertura del vocabulario (p10 / p50 / p90)",
              [("histogram_quantile(%s, sum by (le) (rate(expedientes_cobertura_vocabulario_bucket[2m])))" % q, "p" + str(int(float(q) * 100))) for q in ("0.1", "0.5", "0.9")], _pos(12, 13, 12, 8), "percentunit"),
    ]
    return tablero("expedientes-deriva", "D3 - Data drift", p, "Cambios en los datos de entrada frente a la referencia")


def d5():
    p = [
        stat("Presupuesto de error restante", "clamp_min(1 - (" + ERR.replace("[2m]", "[10m]") + ") / 0.01, 0)", _pos(0, 0, 6, 5), "percentunit", decimales=0,
             umbrales=[{"color": "red", "value": None}, {"color": "orange", "value": 0.25}, {"color": "green", "value": 0.5}],
             desc="SLO 99 % de peticiones sin error 5xx; ventana de demo de 10 min (en produccion, 30 dias)"),
        stat("Consumo del presupuesto (burn rate)", "(" + ERR.replace("[2m]", "[2m]") + ") / 0.01", _pos(6, 0, 6, 5), "x", decimales=1,
             umbrales=[{"color": "green", "value": None}, {"color": "orange", "value": 6}, {"color": "red", "value": 14.4}],
             desc="1x = se consume justo al ritmo permitido; 14,4x dispara la alerta rapida"),
        stat("Alertas en disparo", 'count(ALERTS{alertstate="firing"}) or vector(0)', _pos(12, 0, 6, 5), umbrales=[{"color": "green", "value": None}, {"color": "red", "value": 1}]),
        stat("Alertas en espera (pending)", 'count(ALERTS{alertstate="pending"}) or vector(0)', _pos(18, 0, 6, 5), umbrales=[{"color": "green", "value": None}, {"color": "orange", "value": 1}]),
        serie("Burn rate del SLO de disponibilidad", [("(" + ERR + ") / 0.01", "ventana 2 min"),
                                                       ("(" + ERR.replace("[2m]", "[30s]") + ") / 0.01", "ventana 30 s")],
              _pos(0, 5, 12, 9), "x", umbrales=[{"color": "transparent", "value": None}, {"color": "red", "value": 14.4}], minimo=0),
        serie("Estado de las alertas", [('ALERTS{alertstate="firing"}', "{{alertname}} (disparada)"), ('ALERTS{alertstate="pending"}', "{{alertname}} (pendiente)")],
              _pos(12, 5, 12, 9), minimo=0, maximo=2),
        tabla("Alertas activas ahora", "ALERTS", _pos(0, 14, 24, 8)),
    ]
    return tablero("expedientes-presupuesto", "D5 - Presupuesto de error y alertas", p, "SLO, burn rate y alertas activas")


if __name__ == "__main__":
    os.makedirs(SALIDA, exist_ok=True)
    for nombre, t in (("d1_servicio", d1()), ("d2_modelo", d2()), ("d3_deriva", d3()), ("d5_presupuesto", d5())):
        with open(os.path.join(SALIDA, nombre + ".json"), "w", encoding="utf-8") as f:
            json.dump(t, f, ensure_ascii=False, indent=1)
        print("escrito", nombre)
