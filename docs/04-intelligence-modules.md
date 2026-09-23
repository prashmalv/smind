# The intelligence modules

Fourteen modules. Thirteen from the concept doc, plus `store_vision`, added because the
platform now has cameras and footfall deserves its own reasoning rather than a footnote
inside store intelligence.

Every module answers one of the doc's five questions and produces one business output.

| Key | Title | Question | Business output |
|---|---|---|---|
| `customer_profiling` | Customer profiling | Who is buying? | Customer segments |
| `purchase_behavior` | Purchase behaviour | What are they buying? | Buying patterns |
| `menu_intelligence` | Menu intelligence | What are they buying? | Menu optimisation |
| `basket_analysis` | Basket analysis | What are they buying? | Combo and cross-sell |
| `sentiment_intelligence` | Sentiment intelligence | Why are they buying? | Customer sentiment |
| `voice_of_customer` | Voice of customer | What is stopping them? | Customer pain points |
| `campaign_intelligence` | Campaign intelligence | What should we offer next? | Campaign effectiveness |
| `store_intelligence` | Store intelligence | Who is buying? | Location-level insights |
| `price_sensitivity` | Price sensitivity | Why are they buying? | Pricing and offer insights |
| `competitor_intelligence` | Competitor intelligence | What is stopping them? | Competitive positioning |
| `trend_detection` | Trend detection | What should we offer next? | New product opportunities |
| `churn_intelligence` | Churn intelligence | What is stopping them? | Retention triggers |
| `next_best_offer` | Next best offer | What should we offer next? | Personalised offers |
| `store_vision` | In-store vision | What is stopping them? | Footfall, queue and dwell |

---

## How the interesting ones actually work

### `customer_profiling` — segments that move

RFM over the period, then **rules, not clusters**. A marketing head has to be able to argue
with a segment assignment, and "the k-means put them there" is not an argument. The rules
are ordered: lapsed beats everything (they are not buying at all), then premium, then
frequency, then the behavioural flavours.

Thresholds are derived per tenant from their own distribution — lapsed at the 85th
percentile of recency, premium at the 75th of basket — so a weekly-visit café and a monthly
grocery shop both get sensible cut-offs without configuration.

Segment *movement* is retained (`previous_segment_key`) because who arrived in a segment is
more actionable than who is in it.

### `purchase_behavior` — decompose before explaining

When revenue moves, the module splits it before it says anything: did order count move, or
did average basket? They need different responses and different owners — traffic is a
marketing and operations problem, basket is merchandising and attachment. Reporting "sales
fell 9%" without that split is the thing this product exists to stop.

### `menu_intelligence` — the quadrant, and the category check

Items are placed on the classic menu-engineering quadrant (popularity × margin): star,
workhorse, puzzle, drag. The recommendation differs per quadrant — you do not discount a
star to fix a volume dip, and a puzzle needs menu position rather than a price cut.

When an item declines, the module checks its **category** over the same window. If the
category held, the problem is the item; if the category moved with it, a promotion on that
one item is the wrong response. That comparison is the difference between an insight and a
number.

### `basket_analysis` — lift, and the addressable gap

Association rules with support, confidence and lift. Lift matters because confidence alone
promotes whatever is already popular: fries attach to everything, which is not a finding.

The useful number is the **gap** — baskets containing A without B. That is what a bundle
could convert, and it is what the estimated impact is calculated from.

### `price_sensitivity` — log-log elasticity, honestly bounded

Per-item elasticity from a log-price/log-units regression across days, requiring at least
seven days and three distinct price points. Items that do not clear that bar are reported
as unmodellable rather than given a category default silently.

A **positive** fitted slope is classified `unclear`, never `inelastic`. Units rising with
price is almost always a confound — a promotion running alongside — and labelling it
inelastic would invite a price rise on noise.

### `store_intelligence` — where the camera earns its place

Joins POS orders to camera footfall to produce **conversion**, then compares each store to
the network. When a store is down it can distinguish "fewer people came in" from "the same
people came in and left", and it cross-references queue wait to suggest which.

It also checks whether a decline is concentrated or estate-wide, because those have
opposite responses: a store visit will not fix a network pricing problem.

Without camera data the module still runs and says plainly that conversion cannot be
computed — it does not silently drop the column.

### `voice_of_customer` — volume and sentiment together

Themes ranked by mention count *and* average sentiment. A rare complaint at very low
sentiment and a common complaint at mild sentiment need different responses, so ranking on
either alone misleads.

It also checks time-of-day concentration, which is how the doc's "delivery complaints rose
in the 7–9 PM window" becomes a finding rather than an anecdote.

### `trend_detection` — three signals, and one distinction that matters

1. **Sales momentum** — second half of the period against the first. Catches acceleration
   that a period-over-period comparison averages away.
2. **Theme momentum** — the fixed theme vocabulary rising or falling.
3. **Rising language** — unigrams and bigrams gaining ground in the raw text.

The third exists because themes are a fixed vocabulary, so a preference the business has no
word for yet — exactly the case worth catching — is invisible to them. Bigrams are built
only from words adjacent in the source text; building them from the stopword-filtered list
invents phrases like "fast arrived" out of words that had three stopwords between them.

**A rising complaint is not an emerging preference.** Themes and phrases whose average
sentiment is negative are routed to `rising_complaints`, which voice of customer owns.
Without that split, the same theme appears under "Emerging trend" and "Rising concern" on
the command center, and neither card means anything.

On the seeded estate this produces the doc's flagship example honestly:

```
'spicy chicken' is rising in what customers are writing, up 227% on the prior period.
  15 mentions this period against 5 in the one before, at an average sentiment of 0.62.
  The catalogue already has something matching this language, so the gap is visibility
  rather than range — customers are asking for a thing you sell.
```

### `churn_intelligence` — each customer against their own rhythm

Probability is a function of how far past *their own* expected reorder gap a customer is,
not a flat cut-off. A weekly buyer silent for fourteen days scores higher than a monthly
buyer at the same gap.

Damped by history: a two-order customer is a weaker signal than a twenty-order one, so the
score is weighted by order count. Without that damping the high-risk list fills with people
who bought once.

### `next_best_offer` — priority, not a score

Win-back takes priority over cross-sell. No offer matters if the customer is not coming
back, so a lapsing customer gets a reason to return rather than a bigger basket.

Cross-sell targets the category with the widest gap between the network attachment rate and
this customer's. "Bought a burger" is history; "predictably has not tried the drinks" is
the actionable part.

### `store_vision` — counts into operations

Footfall by hour, queue length, wait, abandonment, dwell and interaction — all from
anonymous aggregate windows.

Wait is derived from occupancy by Little's Law: time in the system equals number in the
system divided by the rate they are served. That is defensible from counts alone, which is
the point — it needs no tracking of individuals.

When it flags a queue peak it checks whether that hour is also the footfall peak. If it is,
the queue is a capacity problem; if it is not, it is a staffing-schedule mismatch. Different
fix, same symptom.

---

## Adding a module

```python
class MyModule(IntelligenceModule):
    key = "my_module"
    title = "My module"
    question = "What is stopping them?"     # one of the five
    business_output = "What it produces"
    reads = "What it analyses"

    def run(self, ctx: AnalysisContext) -> ModuleResult:
        d = ctx.data                         # shared frames, already loaded
        if d.orders.empty:
            return self.empty("Say which source is missing.")
        ...
        result.findings.append(Finding(
            headline="What happened, with the number.",
            reasoning="Why, and what the data does and does not support.",
            actions=[Action("Something ownable.", owner="marketing", effort="low")],
        ))
        return result
```

Register it in `MODULES` in `registry.py`. The parametrised tests pick it up
automatically and will fail it if any finding lacks a reason or an action, or if it emits a
value that is not JSON-safe.
