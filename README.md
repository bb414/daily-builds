# daily-builds

One small, finished project every day, each on its own branch.

## How it works

- `main` holds this index and [`BRIEF.md`](BRIEF.md), which sets out who the projects are for and what makes a good one. Edit the brief to steer future builds.
- Every project lives on its own branch, named `build/YYYY-MM-DD-short-name`, with its own README explaining what it is, why it exists and how to run it.
- Each new build is added to the table below, newest first. The table doubles as the log that stops ideas from repeating.

## Projects

<!-- Each new build goes in a new row directly below the |------| separator line, so the newest is first. -->

| Date | Project | What it does | Theme | Stack | Branch |
|------|---------|--------------|-------|-------|--------|
| 2026-11-24 | Second opinion | Ten-minute scam-spotting test where a scripted AI checker (right 12 times in 16) advises on 16 of 28 invented messages: scores how well you used its advice (switching when it was right, holding firm when it was wrong), replays simple reliance rules on your answers and tracks trust after its first mistake, with a Python toolkit that pools results files, compares advice styles with bootstrap intervals and permutation tests, and estimates study sample sizes by simulation | Human-AI interaction and over-reliance on AI | Offline HTML/JavaScript app, Python (standard library) | [build/2026-11-24-second-opinion](https://github.com/bb414/daily-builds/tree/build/2026-11-24-second-opinion) |
| 2026-11-24 | Pilot purgatory | Interactive simulator of AI pilot portfolios: compare two organisations' pilot practices, watch every pilot's fate in lane charts, trace each stalled pilot to one of five scaling barriers, rank single changes by net value, and stress-test the answer across 11 scenarios | AI adoption and scaling beyond the pilot | Offline HTML/JavaScript app, Python (standard library) | [build/2026-11-24-pilot-purgatory-simulator](https://github.com/bb414/daily-builds/tree/build/2026-11-24-pilot-purgatory-simulator) |
