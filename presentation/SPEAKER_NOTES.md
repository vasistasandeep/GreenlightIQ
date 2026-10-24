# CineROI AI - Interactive Presentation (Speaker Notes)

Open `presentation/index.html` in any browser. One self-contained file, no internet needed.

## Controls
- **Navigate:** the bottom nav bar (Home / prev / next / click any dot to jump / slide counter) works everywhere. On desktop you can also use arrow keys or click the far-left / far-right third of the screen; on phones/tablets, swipe left/right.
- **Expand cards:** click any card with a > chevron to reveal more (clicking a card does NOT advance the slide).
- **Full screen:** press **F**.
- The slider and buttons on slide 5 are fully interactive - arrow keys there move the slider, not the slide.

## The interactive moments (this is what makes it land)
- **Slide 5 - Verdict Machine (the star).** Hand someone the mouse. Drag the price of *The Ledger* (a sample demo title) down from $9.5M. The four checks recompute live and badges flip. At **$7.2M it turns GREENLIGHT** - that is its negotiation ceiling in the demo. Use the "Jump to target deal" button to show it instantly. The story line at the bottom narrates every state. This single slide teaches the whole product.
- **Slides 2, 3, 4, 8, 10, 11 - click-to-reveal cards.** Don't read them aloud; click one and let the reveal do the talking. Keeps the room engaged and the slides uncluttered.

## Flow (13 slides)
1. Title - the hook. "In two slides you'll run a verdict yourself."
2. Problem - click the three pain cards.
3. Big idea - the credit-check analogy; click the three verdicts.
4. Four checks - click each. Punchline: three are price, one is the title itself.
5. **Verdict Machine** - DRAG THE PRICE. Let them play. This is the memorable moment.
6. Explainable AI - intelligence that shows its work. The trust pillars (consistent / explainable / auditable / reproducible). The point: it's AI you can defend.
7. The demo at a glance - the stat cards count up (21 / $259M / 3.60x / 11-3-7). These are illustrative sample-slate figures, not production data.
8. What-If - the negotiation-room sandbox; click the three cards.
9. Keeps itself honest - backtest, recalibrate, govern.
10. The learning layer, measured - click each metric. We fit the demand models to data and the held-out error dropped (WAPE 0.99 -> 0.39, MAPE 99% -> 33%) while the guardrail false-greenlight rate stayed flat. Be upfront: this is a synthetic open-data proxy dataset for the demo, and the fitted version is left inactive by default. The point: the learning layer helps, but never becomes the gate.
11. The AI stack - click each layer: Perception AI (content understanding), Learning AI (models fit to data), Decision AI (the verdict engine), Conversational AI (the Copilot). The line: the AI understands the content and explains the call, while the decision stays transparent and auditable.
12. **Open the live demo portal** - the big green button opens the running product in a new tab. This is the call to action: stop reading, go click it.
13. Close - repeat the one-liner.

## If someone asks "is this really AI?"
Yes - and the best kind for betting millions: **explainable, decision-grade AI**. The AI reads and understands the content (Perception AI), and the Copilot explains every call in plain English (Conversational AI). What sets it apart is that the decision layer is transparent and auditable - you can trace any verdict to the exact number and reproduce it on demand. It's intelligence that shows its work.

## The two lines to leave in the room
- "It's a credit check for content deals - buy, haggle, or walk away, with the receipts."
- "Explainable, decision-grade AI - it understands the content, explains the call, and shows its work every time."

## Setting the "Open the live demo portal" link
The button on slide 12 reads its target from a single constant near the top of the inline `<script>`:
```js
// currently set to a live ngrok tunnel for demos:
const PORTAL_URL = "https://overlabor-stumbling-praising.ngrok-free.dev";
```
- **Sharing the deck as a file or a public link:** leave it `""`. The button shows "Portal opens during a live demo" instead of a dead link - nobody lands on a broken ngrok URL.
- **Presenting live:** set it to wherever the portal is reachable right then - a permanent deployment, `http://localhost:3000` for a local run, or your current https ngrok URL. **ngrok URLs change every time the tunnel restarts**, so re-paste it and push before each demo. The slide shows an amber disclaimer under temporary (ngrok/localhost) links: "Live demo link - only works while a demo is running... if a browser warning appears, tap Visit Site". When sharing the deck for later reading, set it back to `""` so nobody hits a dead tunnel.

## Sharing this deck
It is a single self-contained HTML file (all CSS/JS inline, no assets), so:
- **Email / Slack / Teams:** attach `presentation/index.html`; the recipient double-clicks to open. No internet needed for the deck itself.
- **Public link (GitHub Pages):** `https://vasistasandeep.github.io/GreenlightIQ` (served from this repo via GitHub Pages on `main`).
- **PDF fallback:** browser Print -> Save as PDF (loses all interactivity - use only for read-only recipients).

---

# Capabilities Tour (`presentation/capabilities.html`)

A second, longer deck for **future users and prospects** who want to see *everything* the product does, screen by screen, not just the core verdict story. Same controls and look as `index.html` (bottom nav bar, arrow keys, swipe, click-to-reveal cards, F for full screen, one self-contained file). Open `presentation/capabilities.html` in any browser.

Use `index.html` to **sell the idea** (short, one memorable interactive moment). Use `capabilities.html` to **walk a new user through the whole product**.

## Flow (17 slides)
1. Title - "Everything it can do, one screen at a time." Sets the demo-build expectation.
2. What it is - the credit-check one-liner and the three verdicts.
3. The journey - the four stations (Ingest -> Understand -> Decide -> Defend). Everything else hangs off these.
4. Three ways in - single title, whole slate (CSV/JSON), drop a pitch PDF. Click each.
5. Advanced drivers - the optional sequel/franchise, buzz-level momentum (stage-gated), and macro facts; plus one-click Quick Presets that fill the whole form. Click each.
6. Dashboard - portfolio at a glance; stat cards count up (illustrative sample-slate figures); search / filter / sort / shareable URL.
7. The four checks - efficiency, return, stickiness, payback. Three are price, one is the title. Click each.
8. Title deep-dive - scorecard, deal-stage tracker, one-page PDF, full history, what-if sliders, explain-this. Click each.
9. What-If Explorer - the read-only negotiation sandbox: bear/bull, target deal, shareable link.
10. Backtest Studio - backtest, recalibrate into an immutable version, the version catalog. Click each.
11. Governance - the $25M two-signature sign-off gate and the audit trail.
12. CineROI Copilot - the grounded conversational assistant across the app.
13. The AI stack - Perception / Learning / Decision / Conversational. Click each layer.
14. Trust - consistent, explainable, auditable, reproducible, honest.
15. Works everywhere - responsive, keyboard/a11y, link-native.
16. Open the live demo portal - the call to action (same `PORTAL_URL` constant as the other deck).
17. Close - "One engine, from pitch to sign-off."

## Presenting tips
- Let the **click-to-reveal cards** carry slides 4, 5, 7, 8, 9, 10, 13 - click, do not read.
- Be upfront on slide 1 and slide 6: this is a **demo build on a sample slate**, figures are illustrative.
- The live-portal button on slide 16 reads the same `PORTAL_URL` constant near the top of the inline `<script>` - set it to your deploy URL, `http://localhost:3000`, or the current ngrok link before presenting; leave it `""` when emailing the file.
