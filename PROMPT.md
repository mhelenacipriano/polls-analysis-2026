# Claude Code prompt

Open a terminal in this folder, run `claude`, and paste everything below the line.

---

You're working in `runoff-model`, a small project that forecasts the 25 October 2026 Brazilian presidential runoff (Lula, PT, vs Flávio Bolsonaro, PL) from published polls and shows it as a static dashboard on Vercel. Read `README.md` first, then `data/polls.csv`, `model/simulate.py`, `public/index.html` and `scraper/tse_pesqele.py`.

The goal today: get the project into a GitHub repository deployed on Vercel, make the TSE scraper work against the live site, and bring the poll data up to date. Work through the steps in order, and stop and ask me before anything you can't undo.

## 1. Check that it works as is

- Run `python model/simulate.py --seed 1` and `python scripts/build_dashboard_data.py`.
- Serve `public/` with `python -m http.server -d public 8000` and open it. Check that the odds, the chart, the sliders, the presets and the poll checkboxes all work, in light and dark mode, and at phone width (about 390px) with no sideways scrolling.
- Fix anything broken before moving on.

## 2. GitHub and Vercel

- `git init`, make a first commit, and create a **private** GitHub repository called `runoff-model` with `gh repo create`. Ask me before making it public.
- Deploy with Vercel. If the `vercel` CLI is installed and logged in, run `vercel link` and `vercel --prod`. If not, tell me the dashboard steps (Add New → Project → import the repo; framework preset "Other"; `vercel.json` sets the output to `public`).
- Confirm that the deployed URL loads `polls.json`, and give me the link.

## 3. Make the TSE scraper work

The TSE's public poll registry is a JSF/PrimeFaces form at https://pesqele-divulgacao.tse.jus.br/app/pesquisa/listar.xhtml. The selectors in `scraper/tse_pesqele.py` were guessed from screenshots and haven't run against the real page.

- `pip install -r requirements.txt && playwright install chromium`.
- Open the page with Playwright in headed mode and inspect the real DOM: the "Eleição", "UF", "Cargo" and "Empresa contratada" fields, the registration-period date inputs, the "Pesquisar" button, the results table, the paginator, and the three per-row buttons (magnifier = details, list icon, orange file icon = documents).
- Fix `SELECTORS` and `parse_detail()` to match. Filters: Eleições Gerais 2026, BRASIL, Presidente, registered 05/10/2026 to 25/10/2026.
- Keep it polite: one request at a time, a delay of at least 1.5 seconds between actions, no parallel browsers. If the site shows a captcha or blocks us, stop and tell me; don't try to get around it.
- Write `data/registrations.csv`. Then, with `--pdfs`, download the documents for every registration into `data/pdfs/` (git-ignored).
- Show me a summary table: registration, pollster, contractor, fieldwork, sample, margin of error.

## 4. Check the poll data against the registrations

For each row in `data/polls.csv`, match it to its TSE registration (by number where we have one, otherwise by pollster + fieldwork dates).

- Fill in missing `tse_registration`, `field_dates` and `sample_size`. Known gaps: Indexa/Broadcast has no sample (the model assumes 2000); PoderData Oct 13, Ipespe Oct 17 and Indexa have no fieldwork dates; AtlasIntel Oct 9 and Datafolha Oct 22 have no registration number.
- Flag any registration for a national presidential poll in the period that isn't in `polls.csv`. It's either unpublished or a poll we missed.
- Don't change any vote share based on the registry. The registry has no results. Vote shares only change from a pollster's own report or a news source, with the source link updated in the same row.

## 5. Add the eve-of-vote polls

These were registered for release on 24 October: Datafolha BR-09540/2026, Quaest BR-09158/2026, AtlasIntel BR-06380/2026, Nexus/BTG BR-08234/2026, Palver BR-01794/2026, Veritá BR-03181/2026, Simplex BR-01823/2026, Collecta BR-05601/2026, Franca BR-04863/2026. CNT/MDA is already in.

- For each one that has been published, add a row with Flávio's valid-vote share and a source link. If only total votes are reported, compute `flavio / (flavio + lula) * 100` and say so in the commit message.
- Note that g1 and Folha may block automated fetching; use the pollster's own site or other outlets (CNN Brasil, Gazeta do Povo, Poder360, Metrópoles, Exame).
- Rebuild `public/polls.json`, run the model, and show me the before/after win probabilities.

## 6. Ship

- Commit with a clear message, push, and confirm Vercel redeployed and shows the new polls.
- Make sure the GitHub Action in `.github/workflows/check.yml` passes.
- Finish with: the live URL, the repo URL, the current base-case odds, and a list of anything you couldn't verify.

## Rules

- Never invent a poll number. If you can't find a source, leave the row out and tell me.
- Keep the dashboard's "this is a model, not a prediction" framing.
- Don't add tracking, analytics or a backend. It stays a static site.
- Ask before force-pushing, deleting files, or making the repository public.
