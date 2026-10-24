#!/usr/bin/env python3
"""Scrape registered presidential polls from the TSE's public PesqEle app.

PesqEle (https://pesqele-divulgacao.tse.jus.br/app/pesquisa/listar.xhtml) is a
JSF/PrimeFaces form with no public API, so this drives a real browser.

What it collects: registration number, pollster, contractor, registration date,
planned release date, fieldwork period, sample size, margin of error, and the
registration documents (PDFs). PesqEle holds METHOD, not RESULTS: vote shares
still come from the pollsters' reports or the press (see data/polls.csv).

Run it on your own machine. The TSE may block cloud and datacenter IPs.

  pip install -r requirements.txt && playwright install chromium
  python scraper/tse_pesqele.py --from 05/10/2026 --to 25/10/2026 --headed
  python scraper/tse_pesqele.py --pdfs        # also download each registration's documents

Output: data/registrations.csv (and data/pdfs/<registration>/ with --pdfs).

NOTE: the selectors below were written from screenshots of the form, not from
the live DOM. If a step fails, run with --headed --pause, inspect the element in
the Playwright inspector, and fix the matching selector in SELECTORS.
"""
import argparse
import csv
import re
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
URL = "https://pesqele-divulgacao.tse.jus.br/app/pesquisa/listar.xhtml"

# Label text as it appears on the form (Portuguese). Adjust if the TSE changes the page.
SELECTORS = {
    "eleicao_label": "Eleição",
    "eleicao_value": "Eleições Gerais 2026",
    "uf_label": "UF",
    "uf_value": "BRASIL",
    "cargo_label": "Cargo",
    "cargo_value": "Presidente",
    "periodo_inicio": "input[id*='dataInicio'], input[id*='periodoInicio']",
    "periodo_fim": "input[id*='dataFim'], input[id*='periodoFim']",
    "search_button": "button:has-text('Pesquisar')",
    "results_rows": "table tbody tr[data-ri], table tbody tr[role='row']",
    "next_page": ".ui-paginator-next:not(.ui-state-disabled)",
    "detail_button": "a[title*='Detalh'], button[title*='Detalh'], .fa-search",
    "detail_close": ".ui-dialog-titlebar-close, button:has-text('Fechar'), button:has-text('Voltar')",
}

POLITE_DELAY = 1.5  # seconds between page actions; be gentle with a public court system


def pick_primefaces(page, label_text, option_text):
    """Open the PrimeFaces selectOneMenu next to a label and choose an option by visible text."""
    label = page.locator(f"label:has-text('{label_text}')").first
    menu_id = label.get_attribute("for") or ""
    menu_id = menu_id.removesuffix("_input").removesuffix("_focus")
    trigger = page.locator(f"[id='{menu_id}'] .ui-selectonemenu-trigger") if menu_id else \
        label.locator("xpath=following::div[contains(@class,'ui-selectonemenu')][1]")
    trigger.first.click()
    page.locator(f".ui-selectonemenu-panel:visible li:has-text('{option_text}')").first.click()
    page.wait_for_load_state("networkidle")
    time.sleep(POLITE_DELAY)


def fill_date(page, selector, value):
    box = page.locator(selector).first
    box.click()
    box.fill("")
    box.type(value, delay=40)
    page.keyboard.press("Tab")


def parse_detail(text):
    """Pull structured fields out of a registration's detail panel text."""
    def grab(pattern):
        m = re.search(pattern, text, re.I | re.S)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    return {
        "registration": grab(r"(BR-\d{5}/\d{4})"),
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


def scrape(date_from, date_to, headed=False, pause=False, pdfs=False):
    out_csv = ROOT / "data" / "registrations.csv"
    pdf_dir = ROOT / "data" / "pdfs"
    records = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        ctx = browser.new_context(locale="pt-BR", accept_downloads=True)
        page = ctx.new_page()
        page.goto(URL, wait_until="networkidle")
        if pause:
            page.pause()

        pick_primefaces(page, SELECTORS["eleicao_label"], SELECTORS["eleicao_value"])
        pick_primefaces(page, SELECTORS["uf_label"], SELECTORS["uf_value"])
        try:
            pick_primefaces(page, SELECTORS["cargo_label"], SELECTORS["cargo_value"])
        except PWTimeout:
            print("No 'Cargo' filter found; continuing without it (filter by text later).")
        fill_date(page, SELECTORS["periodo_inicio"], date_from)
        fill_date(page, SELECTORS["periodo_fim"], date_to)
        page.locator(SELECTORS["search_button"]).first.click()
        page.wait_for_load_state("networkidle")
        time.sleep(POLITE_DELAY)

        page_no = 1
        while True:
            rows = page.locator(SELECTORS["results_rows"])
            count = rows.count()
            print(f"Page {page_no}: {count} rows")
            for i in range(count):
                row = rows.nth(i)
                summary = re.sub(r"\s+", " ", row.inner_text()).strip()
                rec = {"row_text": summary}
                try:
                    row.locator(SELECTORS["detail_button"]).first.click()
                    page.wait_for_load_state("networkidle")
                    time.sleep(POLITE_DELAY)
                    detail = page.locator(".ui-dialog:visible, .ui-panel:visible, main").last.inner_text()
                    rec |= parse_detail(detail)
                    if pdfs and rec.get("registration"):
                        target = pdf_dir / rec["registration"].replace("/", "_")
                        target.mkdir(parents=True, exist_ok=True)
                        for link in page.locator("a:has-text('.pdf'), a[href*='download'], a:has(.fa-file)").all():
                            try:
                                with page.expect_download(timeout=15000) as dl:
                                    link.click()
                                d = dl.value
                                d.save_as(target / d.suggested_filename)
                                time.sleep(POLITE_DELAY)
                            except PWTimeout:
                                pass
                    page.locator(SELECTORS["detail_close"]).first.click()
                    page.wait_for_load_state("networkidle")
                except PWTimeout:
                    rec["error"] = "detail view not found"
                records.append(rec)
                print("  ", rec.get("registration") or summary[:80])
            nxt = page.locator(SELECTORS["next_page"])
            if nxt.count() == 0:
                break
            nxt.first.click()
            page.wait_for_load_state("networkidle")
            time.sleep(POLITE_DELAY)
            page_no += 1
        browser.close()

    fields = ["registration", "pollster", "contractor", "registered_on", "release_date",
              "field_start", "field_end", "sample_size", "margin_of_error", "confidence",
              "cost", "row_text", "error"]
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)
    print(f"\nWrote {len(records)} registrations to {out_csv.relative_to(ROOT)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Scrape TSE PesqEle presidential poll registrations.")
    ap.add_argument("--from", dest="date_from", default="05/10/2026", help="registration period start, DD/MM/YYYY")
    ap.add_argument("--to", dest="date_to", default="25/10/2026", help="registration period end, DD/MM/YYYY")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    ap.add_argument("--pause", action="store_true", help="open the Playwright inspector after the page loads")
    ap.add_argument("--pdfs", action="store_true", help="download each registration's documents")
    a = ap.parse_args()
    scrape(a.date_from, a.date_to, a.headed, a.pause, a.pdfs)
