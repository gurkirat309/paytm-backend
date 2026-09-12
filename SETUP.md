# Udhaar Cashflow Brain — external surfaces

Four features, one backend. Build in this order; each one works standalone,
so if you run out of time you stop wherever you are and still have a demo.

---

## Step 1 · Deploy the backend (~10 min)

Push `app.py`, `requirements.txt` and `render.yaml` to a GitHub repo, then on
[render.com](https://render.com) → New → Web Service → point at the repo.
Free tier is fine. Railway or Fly work identically.

You get a URL like `https://udhaar-backend.onrender.com`.

Open it. You should see the dashboard, empty and waiting.

> Free-tier services sleep after inactivity and take ~40s to wake. **Hit the URL
> five minutes before you present** or your first agent call will time out on stage.

In Phinite → **Env. Variables**, add:

```
BACKEND_URL = https://udhaar-backend.onrender.com
```

No trailing slash.

---

## Step 2 · Dashboard (the big one)

Create a new tool `dashboard_tool` in Dev Studio, paste `DASHBOARD_TOOL` from
`phinite_tools.py`, and attach it to **every** agent.

Then add one line to each agent's prompt:

> After completing your work, call `dashboard_tool` with `agent` set to your own
> name, a one-line `note` describing what you did, and any state you changed.

Per-agent state to pass:

| Agent | keys |
|---|---|
| Collections Prioritization | `collections_queue`, `total_outstanding`, `customers_with_dues`, `concentration_pct`, `concentration_amount` |
| Payment Settlement Matcher | `reconciliation` = `{credited, matched, partial, unmatched}` |
| Cash Flow Analyst | `cash_position` = `{expected_30d, shortfall, verdict}` |
| Everyone else | just `agent` + `note` |

`collections_queue` shape:

```json
[{"name":"Ramesh Kumar","amount":11837,"days":88,"score":28,"level":4}]
```

**Demo it:** dashboard on a second screen, chat on the first. The audience
watches cards populate as agents fire. This single change is what stops it
reading as a chatbot.

---

## Step 3 · WhatsApp (the one that lands hardest)

1. [twilio.com](https://twilio.com) → free trial → Messaging → Try WhatsApp
2. Send the join code from your phone to Twilio's sandbox number
3. Copy Account SID and Auth Token into Render → Environment
4. Replace `message_sending_tool` with `MESSAGE_SENDING_TOOL`
5. Put the phone number that joined the sandbox into the `PHONES` dict

Guardrails are unchanged — quiet hours and frequency caps still block in code.
The difference is that a *permitted* message now actually arrives.

**Demo it:** hand a judge the phone. Run collections. Let it buzz in their hand.
Then run the same flow with `override_hour: 23` and let them watch it refuse.

Without Twilio credentials the backend logs to the dashboard instead of sending,
so this degrades gracefully if the wifi dies.

---

## Step 4 · PDF statement

Create `statement_tool`, paste `STATEMENT_TOOL`, attach it to the Customer Name
Resolver and Collections Prioritization Engine. Add to their prompts:

> If the merchant asks for a statement, hisaab, or parchi for a customer, call
> `ledger_database_tool` with `read_customer` for their entries, then call
> `statement_tool` with `customer_name`, `entries` and `open_amount`.

Triggers: *"Ramesh ka hisaab nikalo"*, *"statement banao"*.

Open `BACKEND_URL/statement/generate` to see the output. It's a proper
letterheaded statement in your brand colours — the thing shopkeepers currently
tear out of a notebook.

---

## Step 5 · Soundbox voice

Create `soundbox_tool`, paste `SOUNDBOX_TOOL`, attach to Payment Settlement
Matcher and Cash Flow Analyst. Add to their prompts:

> After reporting, call `soundbox_tool` with a `text` of at most two spoken
> sentences summarising the outcome in Hindi. Write it the way a person speaks,
> not the way a report reads.

Good: `"Aaj ₹4,792 aaya. Ramesh ne ₹2,000 diye, ab ₹11,837 baaki. Ek payment
₹450 match nahi hua."`

The endpoint returns real Hindi audio via gTTS and the text lands on the
dashboard's Soundbox card either way.

---

## Demo order (matters)

Run **collections before reconciliation**. Tool state resets between Phinite
test sessions, so balances only ever go down if you run it this way. In the
other order a sharp judge will spot numbers that disagree.

```
1. Ramesh ko do sau udhaar     → the two-Ramesh stop, the credit-limit warning
2. kaun baaki hai              → queue populates on the dashboard, 80% line
3. [approve a reminder]        → phone buzzes in the judge's hand
4. [same, override_hour 23]    → blocked, live, on the dashboard feed
5. check payments              → reconciliation, partial applied, ₹450 unmatched
6. Diwali stock ke liye paisa? → Soundbox speaks the verdict
```

Screenshot every beat as you get it working. Live demos fail; screenshots don't.

---

## If time runs out

Ship steps 1–3. Dashboard plus real WhatsApp delivery is already the difference
between a chat transcript and a product. PDF and voice are upside.
