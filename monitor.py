"""
Monitor Ticketag Pisa - Curva Nord
Apre la pagina della partita con un browser vero (Playwright), legge i posti in
rivendita e manda una notifica push via ntfy.sh quando compare un posto NUOVO
in Curva Nord.

Variabili d'ambiente:
  TICKETAG_URL  link della partita
  NTFY_TOPIC    nome del canale ntfy
  SECTOR        settore da cercare (default "Curva Nord")
  INTERVAL      secondi tra un controllo e l'altro (default 60)
  DURATION      secondi totali di esecuzione, 0 = all'infinito (default 0)
"""
import base64, datetime, json, os, re, time
import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("TICKETAG_URL") or \
      "https://pisa-ticketag.ticketone.it/Partita/6a25c494-e1ef-461e-86f4-1da67a546010?tickets=1"
TOPIC = os.environ["NTFY_TOPIC"]
SECTOR = os.environ.get("SECTOR", "Curva Nord")
INTERVAL = int(os.environ.get("INTERVAL", "60"))
DURATION = int(os.environ.get("DURATION", "0"))

def log(msg):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)

def notify(title, body):
    try:
        requests.post(f"https://ntfy.sh/{TOPIC}", data=body.encode(), timeout=10, headers={
            "Title": title, "Priority": "urgent",
            "Tags": "ticket,rotating_light", "Click": URL})
    except Exception as e:
        log(f"Errore notifica: {e}")

def save_debug(content):
    """Salva un file debug.txt nel repo, per l'analisi."""
    tok, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (tok and repo):
        return
    url = f"https://api.github.com/repos/{repo}/contents/debug.txt"
    h = {"Authorization": f"token {tok}", "Accept": "application/vnd.github+json"}
    sha = requests.get(url, headers=h, timeout=10).json().get("sha")
    data = {"message": "debug", "content": base64.b64encode(content.encode()).decode()}
    if sha:
        data["sha"] = sha
    requests.put(url, headers=h, json=data, timeout=10)

def parse_seats(text):
    """Ogni posto in pagina finisce con 'PRENDI IL POSTO'. Tiene solo quelli del settore."""
    seats = []
    for block in text.split("PRENDI IL POSTO"):
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        # il blocco del posto inizia con "<Settore> n° XX"
        start = next((i for i, l in enumerate(lines) if re.match(rf"{re.escape(SECTOR)} n°", l, re.I)), None)
        if start is not None:
            seats.append(" | ".join(lines[start:]))
    return seats

def main():
    start, seen, first = time.time(), set(), True
    tickets_json = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="it-IT", user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"))
        page = ctx.new_page()

        def on_resp(r):  # conserva i dati grezzi dei biglietti per il debug
            if r.url.endswith("/tickets") or "/tickets?" in r.url:
                try: tickets_json["data"] = r.json()
                except Exception: pass
        page.on("response", on_resp)

        while True:
            try:
                page.goto(URL, wait_until="networkidle", timeout=45000)
                page.wait_for_timeout(2000)
                text = page.inner_text("body")
                seats = parse_seats(text)
                new = [s for s in seats if s not in seen]
                if new and not first or (first and seats):
                    msg = "\n".join(new or seats)
                    log(f"POSTI {SECTOR.upper()} NUOVI:\n{msg}")
                    notify(f"{SECTOR}: {len(new or seats)} posto/i su Ticketag!", msg)
                else:
                    log(f"{SECTOR}: {len(seats)} posti in vendita, nessuno nuovo.")
                if first or set(seats) != seen:
                    try:
                        save_debug(f"Aggiornato: {datetime.datetime.now()}\n\n== {SECTOR} ==\n"
                                   + "\n".join(seats) + "\n\n== JSON tickets ==\n"
                                   + json.dumps(tickets_json.get("data"), ensure_ascii=False, indent=1)[:60000])
                    except Exception as e:
                        log(f"Errore debug: {e}")
                seen, first = set(seats), False
            except Exception as e:
                log(f"Errore controllo: {e}")
            if DURATION and time.time() - start > DURATION:
                break
            time.sleep(INTERVAL)
        browser.close()

if __name__ == "__main__":
    main()
