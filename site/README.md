# The portfolio website

This folder builds a public website from the projects in this repository: a home page with every project, searchable and grouped by topic, a list by month, an about page, and a page for each project with tabs to **try it** (the real app, embedded and running in the visitor's browser), read **how it works** (its README), read its **findings** (if it has a FINDINGS.md) and step through a **screenshot tour**. A project with no app gets the tour instead, so visitors still see what it does.

It rebuilds itself. Every daily build adds a row to the table in the main README, and that change to `main` starts the workflow in `.github/workflows/site.yml`, which builds the site and publishes it with GitHub Pages. It also runs once a day as a backstop, and you can run it by hand from the Actions tab ("Build the portfolio site", then "Run workflow").

Only the apps, screenshots, example outputs and write-ups are published. Source code is never copied, so the repository can stay private.

## Switching it on

GitHub Pages can publish from a private repository on GitHub Pro, which is free for students through the GitHub Student Developer Pack.

1. Apply for the Student Developer Pack at education.github.com/pack and wait for it to be approved (GitHub Pro comes with it).
2. In this repository, open Settings, then Pages. Under "Build and deployment", set Source to "GitHub Actions".
3. Open the Actions tab, choose "Build the portfolio site" and click "Run workflow".

The site then appears at `https://bb414.github.io/daily-builds/`, and every new build appears on it automatically. Until Pages is switched on, the workflow still builds and tests the site but skips publishing, with a note in the run's summary.

## Changing what it says

Everything you might want to edit is in `site.json`:

- `name`, `title`, `tagline`, `how`, `about`, `footer`, `projectNote`: the words on the site.
- `links`: links shown on the about page (add LinkedIn, for example).
- `featured`: up to three build branches shown under "Start with these". Change these to your favourites.
- `categories`: the topics. A project goes in the first topic whose keywords appear in its Theme in the index, so new themes sort themselves.
- `categoryOverrides`: put a project in a different topic, for example `"build/2026-11-24-range-finder": "consulting"`.
- `taglines`: replace a project's one-line hook, for example `"build/2026-11-24-ai-act-triage": "Where does your AI system sit under the EU AI Act?"`.

## Building it on your own computer

```bash
git fetch --depth=1 origin '+refs/heads/build/*:refs/remotes/origin/build/*'
pip install -r site/requirements.txt
python site/build_site.py --out _site --cache .site-cache
python -m unittest discover -s site -p "test_*.py"
```

Then open `_site/index.html`. The `--cache` folder keeps shrunk screenshots between builds, so later builds take about a second.

## Growing to thousands of projects

The home page loads 24 projects at a time and filters the rest in the browser. Screenshots are resized and compressed as they are published, which keeps each project to well under 1 MB, so the site stays under GitHub Pages' 1 GB limit for well over a thousand projects. The builder prints the site's size every time and warns if it passes 800 MB.
