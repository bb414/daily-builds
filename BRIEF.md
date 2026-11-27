# Brief for daily builds

This file tells each daily run who the projects are for and what a good one looks like. Benjamin can edit it at any time; the next run picks up the changes.

## Who this is for

Benjamin Brighton, final-year BSc Business and Management with Legal Studies student at the University of Sussex (first-class average), applying for AI-focused master's programmes for 2027.

The question that drives his work: **why does AI so often stall at the pilot stage, in companies and in people's everyday lives?**

Background worth drawing on:

- **Research:** Junior Research Associate on "AI Transformation Frameworks and Organisational Pathways" (interviews with senior executives; finding that AI strategy is often written after the pilots, and that unclear ROI, hard-to-measure benefits, technical complexity and long timescales block scaling). Dissertation "Helper or Crutch? Young People and an AI Scam Checker", a randomised experiment on whether an AI scam checker sharpens or weakens 16 to 18-year-olds' own judgement, within Pound Wise, a financial-literacy programme for young people.
- **Industry:** business process consulting in EPAM's global sales function, building internal AI tools, a CRM pipeline report and a hiring dashboard, and teaching AI fluency and prompt engineering classes.
- **Business:** co-founder and director of a Singapore confectionery retailer, grown from an online shop to 10 outlets using demand-forecasting and ROI models.
- **Study:** AI in Business summer schools at Mannheim ("Green Forecasting": prediction markets, digital twins, explainable AI with SHAP) and Warsaw (Python, R, ML, LLMs, EU AI regulation).
- **Leadership:** founder of the Sussex Consulting Society, trading challenge lead (Bloomberg Global and CME Group challenges), rugby captain, IBM AI Builders Challenge team lead.
- **Languages:** English, Czech, Slovak, basic Mandarin.

## Genuinely useful, first and foremost

Every build is a **tool that someone actually uses for a real job**, not a simulation or a model of an invented world. Before picking an idea, it must pass this test:

1. **Who uses it?** A specific person: Benjamin, or people like him and around him (students, society committees, team captains, consultants, small shop owners, job and master's applicants, trading challenge teams).
2. **What real task does it do?** Something they already do by hand, in a messy spreadsheet or not at all, and would happen anyway this month.
3. **What goes in?** Their own real inputs: pasted text, an uploaded CSV or export from a tool they already use, or details typed into a form.
4. **What do they walk away with?** Something they can act on or hand on: a file, a plan, a draft, a checklist, a schedule, a decision with its reasons, or a calculation they can trust.
5. **Would they open it again?** The best builds get used every week, or every time the task comes round.

If the honest answer to any of these is vague, or the main output is "watch what happens when invented agents, customers or markets play out", pick another idea. Modelling, forecasting and statistics are welcome when they serve the job (a forecast from your own sales export, a risk check on your own trades), but never as the whole point. Every tool opens with realistic sample data loaded, so a visitor sees it working straight away, and has an obvious way to swap in your own.

## Research interests (priority themes)

1. AI adoption and scaling beyond the pilot (for example: a use-case intake and scoring sheet a team actually fills in, a pilot business case built from your own numbers)
2. Human-AI interaction and over-reliance on AI (for example: tools that help people check, review or log the AI output they rely on at work)
3. AI in consumer fintech and digital financial literacy (for example: making sense of your own bank export, subscriptions, student budgets and bills)
4. Innovation management (for example: an idea pipeline or stage-gate board a team runs on)
5. AI governance and regulation, EU AI Act and UK approach (for example: drafting an AI use policy, a register of AI tools in use, screening checklists)

## Wider themes to rotate through

- Consulting toolkits (case interview practice, structuring, slide storylines, market sizing worksheets, society case competitions)
- Markets and trading (trade journals, position sizing and risk for trading challenges, analysing your own trade history)
- Retail operations and forecasting (reorder planning, waste and shelf life, rotas and store ROI, from your own sales export)
- Sustainability and carbon (footprints of real events, travel or purchases; carbon reporting checklists)
- Explainable AI and decision-making tools (weighing a real decision, explaining a model on your own data)
- Sales operations and CRM analytics (cleaning and reviewing your own CRM export; sample data always synthetic)
- Team and sports leadership (squad availability and selection, training attendance, fixtures and travel)
- Language learning (drills and spaced repetition from your own vocabulary lists in Czech, Slovak or Mandarin)
- Study and careers (application trackers, tailoring a CV to a job description, revision planners, reading lists and referencing)
- Societies and events (event run sheets, committee task boards, sponsor outreach, budgets and attendance)
- Occasionally, just for fun: Minecraft tools (redstone, schematics, floating-island builds). At most one build in seven.

Usefulness comes before theme. Aim for about half the builds on the priority research themes, always as tools someone working in that area would use, and half on the wider themes. Don't use the same theme two days running.

## Stack: two versions where it makes sense

- **Every build has a browser app** written in HTML, CSS and JavaScript: one self-contained file that works offline when you double-click it. This is the version anyone can open and use.
- **Most builds also get a companion version in another language**, usually Python (R is fine for statistics-heavy ideas). Add it when it does something useful the browser app can't do as well: processing a whole folder of exports at once, a command-line tool for a regular job, heavier data processing, exportable reports, or a reusable package. Skip it when it would add nothing, and say why.
- **When the same logic exists in both versions, tests must prove they agree.** Keep the browser app's core logic in one clearly marked block so it can be run and tested outside the browser.
- **The README explains the split**: which language does what, and roughly how much of each there is.

## What a good build looks like

- **Useful.** It passes the test at the top of this brief: a real person, a real task, their own inputs, something they walk away with.
- **Small but finished.** Something a person could open in a minute and get real value from on their own data.
- **Handles real inputs.** Accepts the messy versions people actually have (extra columns, blank cells, different date formats, the export formats of common tools) and explains clearly what it couldn't read. Anything loaded stays on the user's device.
- **Hands something back.** Exports or copies its result in a form people can use elsewhere: CSV, a calendar file, a printable page, text ready to paste. Work can be saved and reopened.
- **A good UI, always.** Every build ships a polished, interactive interface someone can open and use straight away: ideally a self-contained HTML app that works offline by double-clicking the file, or a local web app started with one command. A command-line tool on its own is not enough. Clean layout, clear typography, responsive on a phone, keyboard accessible, readable charts.
- **Refined, not rushed.** After the first working version, every build goes through at least five refinement loops: two that add depth, one focused purely on the UI, then two that audit everything in great detail.
- **Runs offline with no API keys or paid services.** The tool works on the user's own data; the sample data it ships with is synthetic or openly licensed. If a free public API is genuinely central to the idea, it must fail gracefully when offline.
- **Tested.** Includes at least a few automated tests or a self-check, and they pass before anything is pushed.
- **Explains itself.** README covers who it's for and the job it does, how to use it on your own data (including what format the input should be in), why it matters (linked to the themes above), and what could come next.
- **Entirely unique.** Every build must be a completely different project from every previous one. Themes can come round again, but the core idea, the problem it solves, how it works and what it produces must not overlap any earlier build. No variants, sequels, re-skins or extensions of past builds. No generic tutorial projects either (to-do lists, weather apps, basic calculators, plain chatbots): each one needs its own distinctive angle.
- **Nothing confidential or personal.** No EPAM, client or employer data, no real people's personal data, nothing that imitates a real organisation's branding.

## Writing style

British English. Natural, readable prose. No em dashes.
