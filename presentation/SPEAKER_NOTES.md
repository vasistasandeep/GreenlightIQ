# CineROI AI - Interactive Presentation (Speaker Notes)

Open `presentation/index.html` in any browser. One self-contained file, no internet needed.

## Controls
- **Navigate:** the bottom nav bar (Home / prev / next / click any dot to jump / slide counter) works everywhere. On desktop you can also use arrow keys or click the far-left / far-right third of the screen; on phones/tablets, swipe left/right.
- **Expand cards:** click any card with a > chevron to reveal more (clicking a card does NOT advance the slide).
- **Full screen:** press **F**.
- The slider and buttons on slide 5 are fully interactive - arrow keys there move the slider, not the slide.

## The interactive moments (this is what makes it land)
- **Slide 5 - Verdict Machine (the star).** Hand someone the mouse. Drag the price of *The Ledger* (a sample demo title) down from $9.5M. The four checks recompute live and badges flip. At **$7.2M it turns GREENLIGHT** - that is its negotiation ceiling in the demo. Use the "Jump to target deal" button to show it instantly. The story line at the bottom narrates every state. This single slide teaches the whole product.
- **Slides 2, 3, 4, 8, 10 - click-to-reveal cards.** Don't read them aloud; click one and let the reveal do the talking. Keeps the room engaged and the slides uncluttered.

## Flow (12 slides)
1. Title - the hook. "In two slides you'll run a verdict yourself."
2. Problem - click the three pain cards.
3. Big idea - the credit-check analogy; click the three verdicts.
4. Four checks - click each. Punchline: three are price, one is the title itself.
5. **Verdict Machine** - DRAG THE PRICE. Let them play. This is the memorable moment.
6. Explainable AI - intelligence that shows its work. The trust pillars (consistent / explainable / auditable / reproducible). The point: it's AI you can defend.
7. The demo at a glance - the stat cards count up (21 / $259M / 3.60x / 11-3-7). These are illustrative sample-slate figures, not production data.
8. What-If - the negotiation-room sandbox; click the three cards.
9. Keeps itself honest - backtest, recalibrate, govern.
10. The AI stack - click each layer: Perception AI (content understanding), Decision AI (the verdict engine), Conversational AI (the Copilot). The line: the AI understands the content and explains the call, while the decision stays transparent and auditable.
11. **Open the live demo portal** - the big green button opens the running product in a new tab. This is the call to action: stop reading, go click it.
12. Close - repeat the one-liner.

## If someone asks "is this really AI?"
Yes - and the best kind for betting millions: **explainable, decision-grade AI**. The AI reads and understands the content (Perception AI), and the Copilot explains every call in plain English (Conversational AI). What sets it apart is that the decision layer is transparent and auditable - you can trace any verdict to the exact number and reproduce it on demand. It's intelligence that shows its work.

## The two lines to leave in the room
- "It's a credit check for content deals - buy, haggle, or walk away, with the receipts."
- "Explainable, decision-grade AI - it understands the content, explains the call, and shows its work every time."

## Setting the "Open the live demo portal" link
The button on slide 11 reads its target from a single constant near the top of the inline `<script>`:
```js
// currently set to a live ngrok tunnel for demos:
const PORTAL_URL = "https://overlabor-stumbling-praising.ngrok-free.dev";
```
- **Sharing the deck as a file or a public link:** leave it `""`. The button shows "Portal opens during a live demo" instead of a dead link - nobody lands on a broken ngrok URL.
- **Presenting live:** set it to wherever the portal is reachable right then - a permanent deployment, `http://localhost:3000` for a local run, or your current https ngrok URL. **ngrok URLs change every time the tunnel restarts**, so re-paste it and push before each demo. The slide shows an amber disclaimer under temporary (ngrok/localhost) links: "Live demo link - only works while a demo is running... if a browser warning appears, tap Visit Site". When sharing the deck for later reading, set it back to `""` so nobody hits a dead tunnel.

## Sharing this deck
It is a single self-contained HTML file (all CSS/JS inline, no assets), so:
- **Email / Slack / Teams:** attach `presentation/index.html`; the recipient double-clicks to open. No internet needed for the deck itself.
- **Public link (GitHub Pages):** `https://vasistasandeep.github.io/GreenlightIQ/presentation/` (served from this repo once Pages is enabled on `main`).
- **PDF fallback:** browser Print -> Save as PDF (loses all interactivity - use only for read-only recipients).