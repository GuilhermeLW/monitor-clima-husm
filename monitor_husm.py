import json
import os
import urllib.request
from datetime import datetime

# Monitor Climático 24h - HUSM / Santa Maria, RS
# Fontes: Open-Meteo (Agora + Previsão 72h) e INMET
LAT, LON = -29.6839, -53.8069
IBGE_SANTA_MARIA = "4316907"

# Limiares alinhados ao PCMCE do HUSM (Quadro 11)
LIMIAR_CHUVA = 30.0   # mm/h (Mobilização A4)
LIMIAR_CAPE = 1500.0  # J/kg (Risco de granizo)
LIMIAR_VENTO = 60.0   # km/h (Mobilização A7)
LIMIAR_TEMP = 34.0    # °C (Calor extremo A3)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()


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


def avaliar_ponto(temp, sens, chuva, code, rajada, cape):
    motivos = []
    trovoada = code in (95, 96, 97, 99)
    granizo_cod = code in (96, 99)
    granizo_cape = cape >= LIMIAR_CAPE and (chuva > 0.5 or trovoada or rajada >= 45)

    if trovoada or chuva >= LIMIAR_CHUVA:
        motivos.append(f"Temporal/Chuva ({chuva:.1f} mm/h, WMO {code})")
    if granizo_cod or granizo_cape:
        motivos.append(f"Risco de Granizo (CAPE {round(cape)} J/kg)")
    if rajada >= LIMIAR_VENTO:
        estagio = "Alerta >80" if rajada > 80 else "Mobilização 60-80"
        motivos.append(f"Rajadas A7 [{estagio}] ({round(rajada)} km/h)")
    if temp >= LIMIAR_TEMP or sens >= LIMIAR_TEMP:
        motivos.append(f"Calor A3 ({temp:.1f}°C / sens. {sens:.1f}°C)")

    severo = granizo_cod or granizo_cape or trovoada or rajada >= LIMIAR_VENTO + 15 or chuva >= LIMIAR_CHUVA * 1.5
    return motivos, ("SEVERO" if severo else "ATENÇÃO")


def checar_open_meteo():
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}"
        "¤t=temperature_2m,apparent_temperature,precipitation,weather_code,wind_gusts_10m"
        "&hourly=temperature_2m,apparent_temperature,precipitation,weather_code,wind_gusts_10m,cape"
        "&timezone=America%2FSao_Paulo&forecast_days=3"
    )
    with urllib.request.urlopen(url, timeout=15) as r:
        dados = json.loads(r.read().decode())

    cur = dados["current"]
    hr = dados["hourly"]
    agora = datetime.strptime(cur["time"][:16], "%Y-%m-%dT%H:%M")
    cur_idx = min(
        range(len(hr["time"])),
        key=lambda i: abs((datetime.strptime(hr["time"][i][:16], "%Y-%m-%dT%H:%M") - agora).total_seconds()),
    )

    iminentes, _ = avaliar_ponto(
        cur["temperature_2m"],
        cur["apparent_temperature"],
        cur["precipitation"],
        cur["weather_code"],
        cur["wind_gusts_10m"],
        hr["cape"][cur_idx] or 0,
    )

    janelas = []
    for i in range(cur_idx + 1, min(len(hr["time"]), cur_idx + 72)):
        motivos, nivel = avaliar_ponto(
            hr["temperature_2m"][i],
            hr["apparent_temperature"][i],
            hr["precipitation"][i],
            hr["weather_code"][i],
            hr["wind_gusts_10m"][i],
            hr["cape"][i] or 0,
        )
        if motivos:
            dt = datetime.strptime(hr["time"][i][:16], "%Y-%m-%dT%H:%M").strftime("%d/%m %Hh")
            janelas.append(f"{dt} [{nivel}]: " + " • ".join(motivos))

    return iminentes, janelas


def checar_inmet():
    url = "https://radarmeteorologico.com.br/api/v1/alertas?uf=RS"
    with urllib.request.urlopen(url, timeout=15) as r:
        dados = json.loads(r.read().decode())
    return [
        f"INMET ({a.get('severidade', 'Aviso')}): {a.get('evento', 'Alerta oficial')}"
        for a in dados.get("alertas", [])
        if IBGE_SANTA_MARIA in [str(m) for m in a.get("municipios_afetados", [])]
    ]


if __name__ == "__main__":
    if os.environ.get("SIMULAR_ALERTA") == "true":
        msg = (
            "ALERTA CLIMA HUSM / SANTA MARIA RS\n\n"
            "🚨 RISCO IMINENTE (AGORA):\n"
            "- [SIMULAÇÃO] Temporal/Chuva (35.0 mm/h, WMO 99)\n"
            "- [SIMULAÇÃO] Risco de Granizo (CAPE 2200 J/kg)\n"
            "- [SIMULAÇÃO] Rajadas A7 [Alerta >80] (84 km/h)\n\n"
            "🕒 JANELAS DE RISCO PREVISTAS (72h - 2h no total):\n"
            "- [SIMULAÇÃO] Próx. hora [SEVERO]: Temporal • Granizo\n"
            "- [SIMULAÇÃO] +2h [ATENÇÃO]: Rajadas A7 (68 km/h)"
        )
        enviar_telegram(msg)
    else:
        iminentes, janelas, inmet = [], [], []
        try:
            iminentes, janelas = checar_open_meteo()
        except Exception as e:
            print(f"Erro Open-Meteo: {e}")
        try:
            inmet = checar_inmet()
        except Exception as e:
            print(f"Erro INMET: {e}")

        partes = []
        if iminentes or inmet:
            partes.append("🚨 RISCO IMINENTE (AGORA):\n- " + "\n- ".join(iminentes + inmet))
        if janelas:
            resumo = "\n- ".join(janelas[:8])
            extra = f"\n... (+{len(janelas) - 8} horas com risco nas 72h)" if len(janelas) > 8 else ""
            partes.append(f"🕒 JANELAS DE RISCO PREVISTAS (72h - {len(janelas)}h no total):\n- {resumo}{extra}")

        if partes:
            enviar_telegram("ALERTA CLIMA HUSM / SANTA MARIA RS\n\n" + "\n\n".join(partes))
        else:
            print("HUSM / Santa Maria RS: Normalidade nas próximas 72h.")
