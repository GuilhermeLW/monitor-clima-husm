import json
import os
import urllib.request
import xml.etree.ElementTree as ET

LAT, LON = -29.6839, -53.8069
IBGE_SANTA_MARIA = "4316907"

# Limiares alinhados ao PCMCE do HUSM (Quadro 11)
LIMIAR_CHUVA = 30.0   # mm/h (Mobilização A4)
LIMIAR_CAPE = 1500.0  # J/kg (Risco de granizo)
LIMIAR_VENTO = 60.0   # km/h (Mobilização A7)
LIMIAR_TEMP = 34.0    # °C (Calor extremo A3)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def enviar_telegram(texto):
    print(texto)
    if not TOKEN or not CHAT_ID:
        print("Secrets do Telegram não configurados.")
        return
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data=json.dumps({"chat_id": CHAT_ID, "text": texto}).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=15)


def checar_open_meteo():
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}"
        "¤t=temperature_2m,apparent_temperature,precipitation,weather_code,wind_gusts_10m"
        "&hourly=cape&timezone=America%2FSao_Paulo&forecast_days=1"
    )
    with urllib.request.urlopen(url, timeout=15) as r:
        dados = json.loads(r.read().decode())
    cur = dados["current"]
    cape = dados["hourly"]["cape"][0] or 0
    alertas = []

    if cur["weather_code"] in (95, 96, 97, 99) or cur["precipitation"] >= LIMIAR_CHUVA:
        alertas.append(f"Chuva/Temporal: {cur['precipitation']} mm/h (WMO {cur['weather_code']})")
    if cur["weather_code"] in (96, 99) or (cape >= LIMIAR_CAPE and cur["precipitation"] > 0.5):
        alertas.append(f"Risco de Granizo (CAPE {cape} J/kg)")
    if cur["wind_gusts_10m"] >= LIMIAR_VENTO:
        estagio = "Alerta >80 km/h" if cur["wind_gusts_10m"] > 80 else "Mobilização 60-80 km/h"
        alertas.append(f"Rajadas A7 ({estagio}): {cur['wind_gusts_10m']} km/h")
    if cur["temperature_2m"] >= LIMIAR_TEMP or cur["apparent_temperature"] >= LIMIAR_TEMP:
        alertas.append(f"Calor A3: {cur['temperature_2m']}°C (sensação {cur['apparent_temperature']}°C)")
    return alertas


def checar_inmet():
    url = "https://radarmeteorologico.com.br/api/v1/alertas?uf=RS"
    with urllib.request.urlopen(url, timeout=15) as r:
        dados = json.loads(r.read().decode())
    alertas = []
    for a in dados.get("alertas", []):
        muns = [str(m) for m in a.get("municipios_afetados", [])]
        if IBGE_SANTA_MARIA in muns:
            alertas.append(f"INMET ({a.get('severidade', 'Aviso')}): {a.get('evento', 'Alerta oficial')}")
    return alertas


def checar_metsul():
    url = "https://metsul.com/categoria/alerta/feed/"
    req = urllib.request.Request(url, headers={"User-Agent": "MonitorHUSM/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        root = ET.fromstring(r.read())
    alertas = []
    for item in root.findall("./channel/item")[:5]:
        titulo = item.findtext("title") or ""
        desc = item.findtext("description") or ""
        texto = f"{titulo} {desc}".lower()
        if any(k in texto for k in ("santa maria", "região central", "rio grande do sul")):
            alertas.append(f"MetSul: {titulo}\n{item.findtext('link') or ''}")
    return alertas


if __name__ == "__main__":
    todos = []
    if os.environ.get("SIMULAR_ALERTA") == "true":
        todos = [
            "[SIMULAÇÃO DE TESTE] Chuva/Temporal: 35.0 mm/h (WMO 99)",
            "[SIMULAÇÃO DE TESTE] Risco de Granizo (CAPE 2200 J/kg)",
            "[SIMULAÇÃO DE TESTE] Rajadas A7 (Alerta >80 km/h): 84 km/h",
        ]
    else:
        for fn in (checar_open_meteo, checar_inmet, checar_metsul):
            try:
                todos.extend(fn())
            except Exception as e:
                print(f"Erro em {fn.__name__}: {e}")

    if todos:
        msg = "ALERTA CLIMA HUSM / SANTA MARIA RS:\n\n- " + "\n- ".join(todos)
        enviar_telegram(msg)
    else:
        print("HUSM / Santa Maria RS: Normalidade.")
