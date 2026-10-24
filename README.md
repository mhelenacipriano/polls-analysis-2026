# Lula–Flávio Runoff Model

A Monte Carlo model of the 25 October 2026 Brazilian presidential runoff, built on published valid-vote polls, with an interactive dashboard hosted on Vercel.

**This is a model, not a prediction.** It shows the range of plausible outcomes under assumptions the viewer controls.

## Layout

```
data/polls.csv                  poll results (one row per poll, source link for each)
data/registrations.csv          TSE registrations (written by the scraper)
model/simulate.py               the model as a command-line script (standard library only)
scripts/build_dashboard_data.py data/polls.csv -> public/polls.json
public/index.html               the dashboard (static; loads polls.json)
public/polls.json               generated; commit it
scraper/tse_pesqele.py          scrapes TSE PesqEle registrations (Playwright)
vercel.json                     serves public/ as a static site
```

## Add or fix a poll

1. Edit `data/polls.csv`. `flavio_valid` is Flávio's share of **valid votes** (blank, null and undecided excluded). If a poll only reports total votes, use `flavio / (flavio + lula) * 100`. `group_a` is 1 for pollsters with the best recent accuracy record (AtlasIntel, Datafolha, Ideia, MDA, Quaest, Real Time Big Data).
2. `python scripts/build_dashboard_data.py`
3. `python model/simulate.py` to check the numbers.
4. Commit `data/polls.csv` and `public/polls.json` and push. Vercel redeploys.

## Run locally

```
python scripts/build_dashboard_data.py
python -m http.server -d public 8000     # then open http://localhost:8000
```

Opening `public/index.html` straight from disk won't work, because the browser blocks `fetch('polls.json')` on `file://` URLs.

## Model

```
python model/simulate.py                       # base case
python model/simulate.py --sigma 3.5           # more polling error
python model/simulate.py --bias -1.5           # shift 1.5 pts toward Lula
python model/simulate.py --all-waves           # count every wave, not just each pollster's latest
```

Weight per poll = `0.5^(days_before_vote / half_life)` × `√min(sample, 5000)` × `1.5 if group A`. Each simulated election draws Flávio's share from `Normal(weighted_mean + bias, sigma)`; win probability is the share of draws above 50%.

## Scraper

PesqEle has the method (sample, fieldwork, margin of error, questionnaire), **not** the results.

```
pip install -r requirements.txt
playwright install chromium
python scraper/tse_pesqele.py --headed                 # watch it run
python scraper/tse_pesqele.py --pdfs                   # also download registration documents
```

Run it from your own machine; the TSE may refuse cloud IPs. The selectors were written from screenshots, so the first run may need fixes (see `--pause`).

## Deploy

1. Push this folder to a new GitHub repository.
2. In Vercel: **Add New → Project**, import the repository. Leave the framework preset as **Other**; `vercel.json` already sets the output directory to `public`.
3. Every push to the main branch redeploys.
