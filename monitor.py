"""
Monitor Ticketag Pisa - Curva Nord
Apre la pagina della partita con un browser vero (Playwright), controlla se
compaiono biglietti e manda una notifica push via ntfy.sh.

Variabili d'ambiente:
  TICKETAG_URL  link della partita
  NTFY_TOPIC    nome del canale ntfy (inventalo lungo e difficile da indovinare)
  INTERVAL      secondi tra un controllo e l'altro (default 60)
  DURATION      secondi totali di esecuzione, 0 = all'infinito (default 0)
"""
import hashlib, os, re, time, datetime
import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("TICKETAG_URL",
      "https://pisa-ticketag.ticketone.it/Partita/6a25c494-e1ef-461e-86f4-1da67a546010?tickets=1")
TOPIC = os.environ["NTFY_TOPIC"]
INTERVAL = int(os.environ.get("INTERVAL", "60"))
DURATION = int(os.environ.get("DURATION", "0"))

# Frasi tipiche di "niente disponibile" (da rifinire guardando i log)
SOLD_OUT = re.compile(r"nessun biglietto|non ci sono biglietti|esaurit|non disponibil|sold out", re.I)
# Un prezzo in pagina = probabile biglietto in vendita
PRICE = re.compile(r"€\s?\d+|\d+[.,]\d{2}\s?€")

def log(msg):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)

def notify(title, body):
    try:
        requests.post(f"https://ntfy.sh/{TOPIC}", data=body.encode(), timeout=10, headers={
            "Title": title, "Priority": "urgent", "Tags": "ticket,rotating_light", "Click": URL})
    except Exception as e:
        log(f"Errore notifica: {e}")

def save_debug(text, api_seen):
    """Salva testo pagina e chiamate API nel repo (debug.txt) per poterle analizzare."""
    tok, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (tok and repo):
        return
    import base64
    body = f"Aggiornato: {datetime.datetime.now()}\n\n== API ==\n" + "\n".join(sorted(api_seen)) + \
           "\n\n== TESTO PAGINA ==\n" + text
    url = f"https://api.github.com/repos/{repo}/contents/debug.txt"
    h = {"Authorization": f"token {tok}", "Accept": "application/vnd.github+json"}
    sha = requests.get(url, headers=h, timeout=10).json().get("sha")
    data = {"message": "debug", "content": base64.b64encode(body.encode()).decode()}
    if sha: data["sha"] = sha
    requests.put(url, headers=h, json=data, timeout=10)

def check(page, api_seen):
    page.goto(URL, wait_until="networkidle", timeout=45000)
    page.wait_for_timeout(2500)  # lascia finire il rendering
    text = page.inner_text("body")
    available = bool(PRICE.search(text)) and not SOLD_OUT.search(text)
    return text, available

def main():
    start, last_hash, first = time.time(), None, True
    api_seen = set()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="it-IT", user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"))
        page = ctx.new_page()
        # Registra le chiamate "dati" dell'app: servono per passare in futuro alla versione leggera
        def on_resp(r):
            if "json" in (r.headers.get("content-type") or "") and r.url not in api_seen:
                api_seen.add(r.url); log(f"API trovata: {r.url}")
        page.on("response", on_resp)

        while True:
            try:
                text, available = check(page, api_seen)
                h = hashlib.md5(text.encode()).hexdigest()
                if first or h != last_hash:
                    log("Testo della pagina:\n" + text[:2000])
                    try: save_debug(text, api_seen)
                    except Exception as e: log(f"Errore debug: {e}")
                if available and h != last_hash:
                    snippet = " ".join(text.split())[:300]
                    log("BIGLIETTI DISPONIBILI! Notifica inviata.")
                    notify("🎟️ Curva Nord disponibile su Ticketag!", snippet)
                elif h != last_hash and not first:
                    log("La pagina è cambiata (nessun biglietto rilevato).")
                else:
                    log("Nessun biglietto.")
                last_hash, first = h, False
            except Exception as e:
                log(f"Errore controllo: {e}")
            if DURATION and time.time() - start > DURATION:
                break
            time.sleep(INTERVAL)
        browser.close()

if __name__ == "__main__":
    main()
