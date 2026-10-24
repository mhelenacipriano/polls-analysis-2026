#!/usr/bin/env python3
"""Scrape registered presidential polls from the TSE's public PesqEle app.

PesqEle (https://pesqele-divulgacao.tse.jus.br/app/pesquisa/listar.xhtml) is a
JSF/PrimeFaces form with no public API, so this drives a real browser.

The form has no "Cargo" field. It has: Eleição, Empresa contratada, UF,
Município, Número de identificação and Período de registro. A search returns at
most 50 rows, so filter by pollster (--pollster) and keep the date window to the
runoff (registered from 05/10/2026, the day after the 4 Oct first round).

PesqEle holds METHOD, not RESULTS: vote shares still come from the pollsters'
reports or the press (see data/polls.csv).

Run it on your own machine. The TSE blocks cloud and datacenter IPs.

  pip install -r requirements.txt && playwright install chromium
  python scraper/tse_pesqele.py --headed --pause --pollster quaest --pollster datafolha --pollster "vox brasil"

Output: data/registrations.csv. The results table was never inspected live, so
the first run also writes data/debug_results.html (git-ignored); if the columns
look wrong, send me its first rows.
"""
import argparse
import csv
import re
import time
import unicodedata
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
URL = "https://pesqele-divulgacao.tse.jus.br/app/pesquisa/listar.xhtml"

# Ids taken from the live form's DOM (JSF ids contain ':' so use [id='...'] selectors).
MENU_ELEICAO = "formPesquisa:eleicoes"
MENU_EMPRESA = "formPesquisa:empresas"
MENU_UF = "formPesquisa:filtroUF"
SELECTORS = {
    "date_inputs": "[id='formPesquisa:camposPesquisa'] span.ui-calendar input",  # [0]=from, [1]=to; readonly
    "search_button": "[id='formPesquisa:idBtnPesquisar']",
    "messages": "[id='formPesquisa:msg']",
    "expired_dialog": ".ui-dialog:visible:has-text('Sessão Expirada')",
    # Not verified against a live results page:
    "results_rows": "form[id='formPesquisa'] tbody tr[data-ri]",
    "results_table": "form[id='formPesquisa'] .ui-datatable",
    "next_page": ".ui-paginator-next:not(.ui-state-disabled)",
    "detail_button": "a[title*='Detalh'], button[title*='Detalh'], .fa-search",
    "detail_close": ".ui-dialog-titlebar-close, button:has-text('Fechar'), button:has-text('Voltar')",
}

ELEICAO = "Eleições Gerais 2026"
UF = "BRASIL"
POLITE_DELAY = 1.5  # seconds between page actions; be gentle with a public court system
MAX_ROWS = 50  # the registry truncates results at this many rows

REG_RE = re.compile(r"[A-Z]{2}-\d{4,5}/\d{4}")


def norm(text):
    """Lowercase and strip accents so 'Veritá' matches 'verita'."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def pause():
    time.sleep(POLITE_DELAY)


def settle(page):
    page.wait_for_load_state("networkidle")
    pause()


def menu_labels(page, menu_id):
    """All option labels of a PrimeFaces selectOneMenu, read from its hidden <select>."""
    return page.eval_on_selector_all(f"[id='{menu_id}_input'] option", "els => els.map(e => e.textContent.trim())")


def pick_menu(page, menu_id, label):
    """Open a PrimeFaces selectOneMenu and click the option whose label matches exactly."""
    page.locator(f"[id='{menu_id}'] .ui-selectonemenu-trigger").click()
    panel = page.locator(f"[id='{menu_id}_panel']")
    panel.wait_for(state="visible")
    # Match on visible text with a regex: no CSS-string escaping, so accents/apostrophes are safe.
    option = panel.locator("li.ui-selectonemenu-item").filter(has_text=re.compile(rf"^\s*{re.escape(label)}\s*$"))
    option.first.click()
    settle(page)


def set_dates(page, date_from, date_to):
    """The date inputs are readonly datepickers, so set the values directly and fire change."""
    page.eval_on_selector_all(
        SELECTORS["date_inputs"],
        "(els, v) => { els[0].value = v[0]; els[1].value = v[1];"
        " els.forEach(e => e.dispatchEvent(new Event('change', {bubbles: true}))); }",
        [date_from, date_to],
    )
    pause()


def find_companies(page, names):
    """Map --pollster substrings to exact 'Empresa contratada' labels (accent/case-insensitive)."""
    labels = menu_labels(page, MENU_EMPRESA)
    found = []
    for name in names:
        hits = [l for l in labels if norm(name) in norm(l)]
        print(f"--pollster {name!r}: {len(hits)} match(es)")
        for h in hits:
            print("    ", h)
            if h not in found:
                found.append(h)
    return found


def check_session(page):
    """The app shows a 'Sessão Expirada' dialog after idling; reload the form if so."""
    if page.locator(SELECTORS["expired_dialog"]).count():
        print("Session expired; reloading the form.")
        page.goto(URL, wait_until="networkidle")
        pause()


def parse_detail(text):
    """Pull structured fields out of a registration's detail panel text (unverified)."""
    def grab(pattern):
        m = re.search(pattern, text, re.I | re.S)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    return {
        "registration": grab(r"([A-Z]{2}-\d{4,5}/\d{4})"),
        "pollster": grab(r"Empresa contratada:?\s*(.+?)\n"),
        "contractor": grab(r"Contratante[^:]*:?\s*(.+?)\n"),
        "registered_on": grab(r"Data de registro:?\s*(\d{2}/\d{2}/\d{4})"),
        "release_date": grab(r"Data de divulga\w+:?\s*(\d{2}/\d{2}/\d{4})"),
        "field_start": grab(r"In[ií]cio da pesquisa:?\s*(\d{2}/\d{2}/\d{4})"),
        "field_end": grab(r"T[ée]rmino da pesquisa:?\s*(\d{2}/\d{2}/\d{4})"),
        "sample_size": grab(r"Quantidade de entrevistados:?\s*([\d.]+)").replace(".", ""),
        "margin_of_error": grab(r"Margem de erro:?\s*([\d,\.]+)"),
        "confidence": grab(r"N[íi]vel de confian\w+:?\s*([\d,\.]+)"),
        "cost": grab(r"Valor[^:]*:?\s*R\$\s*([\d.,]+)"),
    }


def run_search(page, company, date_from, date_to):
    """Fill the form (one company or none) and press Pesquisar."""
    page.goto(URL, wait_until="networkidle")
    pause()
    check_session(page)
    pick_menu(page, MENU_ELEICAO, ELEICAO)
    pick_menu(page, MENU_UF, UF)
    if company:
        pick_menu(page, MENU_EMPRESA, company)
    set_dates(page, date_from, date_to)
    page.locator(SELECTORS["search_button"]).click()
    settle(page)


def read_rows(page, company, debug_path):
    """Return one record per results row: every cell's text plus the raw row text."""
    msg = page.locator(SELECTORS["messages"]).inner_text().strip()
    if msg:
        print("  site message:", msg)
    rows = page.locator(SELECTORS["results_rows"])
    count = rows.count()
    if count >= MAX_ROWS:
        print(f"  WARNING: {count} rows = the registry's cap; results may be truncated. Narrow the dates.")
    table = page.locator(SELECTORS["results_table"])
    if table.count():
        debug_path.write_text(table.first.evaluate("e => e.outerHTML"), encoding="utf-8")
    out = []
    for i in range(count):
        row = rows.nth(i)
        cells = [re.sub(r"\s+", " ", t).strip() for t in row.locator("td").all_inner_texts()]
        text = re.sub(r"\s+", " ", row.inner_text()).strip()
        m = REG_RE.search(text)
        out.append({"company_filter": company or "", "registration": m.group(0) if m else "",
                    "cells": " | ".join(cells), "row_text": text})
    return out


def fetch_details(page, row_index, pdf_dir, want_pdfs):
    """Open one row's details (magnifier) and parse them. Unverified against the live page."""
    rows = page.locator(SELECTORS["results_rows"])
    rows.nth(row_index).locator(SELECTORS["detail_button"]).first.click()
    settle(page)
    detail = page.locator(".ui-dialog:visible, .ui-panel:visible, main").last.inner_text()
    rec = parse_detail(detail)
    if want_pdfs and rec.get("registration"):
        target = pdf_dir / rec["registration"].replace("/", "_")
        target.mkdir(parents=True, exist_ok=True)
        for link in page.locator("a:has-text('.pdf'), a[href*='download'], a:has(.fa-file)").all():
            try:
                with page.expect_download(timeout=15000) as dl:
                    link.click()
                d = dl.value
                d.save_as(target / d.suggested_filename)
                pause()
            except PWTimeout:
                pass
    page.locator(SELECTORS["detail_close"]).first.click()
    settle(page)
    return rec


def scrape(date_from, date_to, headed=False, pause_inspector=False, details=False, pdfs=False, pollsters=()):
    out_csv = ROOT / "data" / "registrations.csv"
    debug_path = ROOT / "data" / "debug_results.html"
    pdf_dir = ROOT / "data" / "pdfs"
    records, seen = [], set()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        ctx = browser.new_context(locale="pt-BR", accept_downloads=True)
        page = ctx.new_page()
        resp = page.goto(URL, wait_until="networkidle")
        if resp is not None and resp.status >= 400:
            raise SystemExit(f"The TSE site answered HTTP {resp.status} (blocked?). Stopping; not retrying.")
        if "Access Denied" in page.content()[:2000]:
            raise SystemExit("The TSE edge returned 'Access Denied'. Stopping; not trying to get around it.")
        if pause_inspector:
            page.pause()

        companies = find_companies(page, pollsters) if pollsters else [None]
        if pollsters and not companies:
            raise SystemExit("No 'Empresa contratada' matched --pollster; try a shorter name.")

        for company in companies:
            print(f"\nSearching {company or 'all companies'} ({date_from} to {date_to})")
            run_search(page, company, date_from, date_to)
            page_no = 1
            while True:
                rows = read_rows(page, company, debug_path)
                print(f"  page {page_no}: {len(rows)} rows")
                for i, rec in enumerate(rows):
                    key = rec["row_text"]
                    if key in seen:
                        continue
                    seen.add(key)
                    if details or pdfs:
                        try:
                            rec |= fetch_details(page, i, pdf_dir, pdfs)
                        except PWTimeout:
                            rec["error"] = "detail view not found"
                    records.append(rec)
                    print("   ", rec.get("registration") or rec["row_text"][:80])
                nxt = page.locator(SELECTORS["next_page"])
                if nxt.count() == 0:
                    break
                nxt.first.click()
                settle(page)
                page_no += 1
        browser.close()

    fields = ["company_filter", "registration", "cells", "pollster", "contractor", "registered_on",
              "release_date", "field_start", "field_end", "sample_size", "margin_of_error",
              "confidence", "cost", "row_text", "error"]
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)
    print(f"\nWrote {len(records)} registrations to {out_csv.relative_to(ROOT)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Scrape TSE PesqEle presidential poll registrations.")
    ap.add_argument("--from", dest="date_from", default="05/10/2026",
                    help="registration period start, DD/MM/YYYY (default: day after the 4 Oct first round)")
    ap.add_argument("--to", dest="date_to", default="25/10/2026", help="registration period end, DD/MM/YYYY")
    ap.add_argument("--pollster", action="append", default=[],
                    help="match 'Empresa contratada' by name (repeatable), e.g. --pollster quaest")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    ap.add_argument("--pause", action="store_true", help="open the Playwright inspector after the page loads")
    ap.add_argument("--details", action="store_true", help="also open each row's details (unverified)")
    ap.add_argument("--pdfs", action="store_true", help="also download each registration's documents (implies --details)")
    a = ap.parse_args()
    scrape(a.date_from, a.date_to, a.headed, a.pause, a.details, a.pdfs, a.pollster)
