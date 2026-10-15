# Music Digest — Interview Questions & Model Answers

> Companion to [`music-digest.md`](./music-digest.md). First-person, 30–90 s answers. 🟢 Easy · 🟡 Medium · 🔴 Hard

**If you only prep 10:** A1, B2, C1, C2, D1, D3, E1, F1, G1, plus the hostile follow-ups.

---

## (a) Project overview & motivation

**A1. 🟢 What is Music Digest?**
> It's a daily briefing pipeline for an independent artist. Every morning a GitHub Action reads around fifty RSS feeds and Google News queries plus about twenty chart pages. It merges duplicate coverage into stories, ranks them by how many outlets covered them, and routes each into one section: superstars, rising, independent, topics, regions or scenes. It also detects chart breakouts, builds a release calendar from date phrases, optionally adds a Claude Haiku summary, and emails two mobile-friendly digests.

**A2. 🟢 Why build it?**
> An artist planning a first release needs to know what's happening without reading thirty sites, especially release timing, so they don't drop on the same Friday as a superstar. Existing newsletters are generic and not tailored to a watch list.

**A3. 🟡 Is it actually used?**
> Yes. It runs on a cron at 00:20 UTC, and the repo history shows thirteen consecutive daily commits from the bot updating its memory file. State is only saved after the email sends successfully, so each of those commits implies a successful run.

**A4. 🟡 What's the most technically interesting part?**
> The de-duplication. About a thousand items a day, where one event gets covered by ten outlets with different headlines. I canonicalise URLs, then cluster titles with token Jaccard similarity plus a fuzzy string-ratio fallback, using an inverted index so each item is only compared against stories sharing a rare word. The number of distinct outlets per story then becomes the main ranking signal.

**A5. 🟢 Where does ML/AI come in?**
> The optional LLM summary (Claude Haiku 4.5) with structured JSON output. The rest is classic NLP and IR: tokenisation, similarity-based clustering, rule-based classification and regex information extraction. I'd describe it as an IR system with an LLM layer, not a trained model.

---

## (b) Architecture & design

**B1. 🟢 Walk me through a run.**
> Load config and state. Compute the lookback window: since the last run minus a two-hour overlap, capped at seven days. Fetch news and charts in parallel with per-host rate limits. Drop items already sent. Cluster into stories, rank, analyse charts, place stories into sections, optionally call the LLM, extract release dates, render HTML, email, then save state. The Action commits the state file back to the repo.

**B2. 🟡 Why store state in a JSON file committed to git?**
> GitHub Actions runners are ephemeral and it had to be free. A committed JSON file is free, durable persistence with history. The trade-off is a large daily diff and git bloat. A KV store or the Actions cache would be cleaner at scale.

**B3. 🟡 Why one section per story instead of showing it everywhere it fits?**
> Readers hate seeing the same story five times. A precedence ladder picks the best home (pinned → biggest → superstar → rising → independent → topic → scene → region), and "chips" show the other angles, like a UK flag or "Hip-hop". The risk is a misrouted story being hidden from the section you'd look in.

**B4. 🟡 How does the chart analysis feed back into news?**
> Breakout artists, meaning non-superstars who are new, jumping 15+ places, or high on Shazam, get turned into name matchers. If a news story mentions one, it's routed to "Rising & breakthrough". So a chart signal improves news classification.

**B5. 🔴 How would you redesign this as a product for 10,000 users?**
> Split it into an ingestion service (shared fetching, clustering and chart parsing once per day for everyone), a per-user personalisation layer (watch lists and section preferences applied as filters and reranking), and a delivery service (SES/SendGrid with bounce handling). Store items, stories and per-user sent-sets in a database. Add click tracking so ranking can be learned. And move the LLM summary to per-cluster summaries that are cached and shared.

---

## (c) Code-level / implementation

**C1. 🔴 Explain `same_story` and its thresholds.**
> Two titles need at least two shared tokens that aren't generic music words like "album" or "tour", so two unrelated "X announces tour" stories don't merge. Then either Jaccard of the token sets is at least 0.45 with three or more shared tokens, or the character-level SequenceMatcher ratio is at least 0.75 with three or more shared tokens. The ratio catches rewordings with high character overlap. The thresholds were set by eye, not tuned on labels.

**C2. 🟡 How do you keep clustering fast?**
> An inverted index from token to stories. For each new item I only look at stories that share a non-generic token, instead of comparing against every story, which is O(n²) on about a thousand items. It's blocking, the same idea as candidate generation in entity resolution.

**C3. 🟡 What's subtle about the clustering order?**
> It's greedy and seed-based. Items are sorted direct-feeds-first and newest-first, each item joins the first matching story, and a story's tokens are its first item's tokens forever. That prevents drift, where a cluster slowly absorbs unrelated items, but it's order-dependent and misses transitive matches. Union-find over the candidate graph would make it order-independent.

**C4. 🟡 How is per-host politeness implemented with threads?**
> A lock per host plus a "last request time" per host. Before each request, a thread takes that host's lock, sleeps until the configured gap has passed (1.2 s for Google News, for example), updates the timestamp and releases. Different hosts proceed in parallel, while the same host is serialised.

**C5. 🟡 How do you parse release dates?**
> Regexes for a release verb followed by a month and day ("out November 14", "drops Friday Oct 17"), parenthetical dates, and relative phrases like "this Friday". The year is resolved heuristically: a date more than 60 days in the past is assumed to mean next year, and dates 3 to 60 days in the past are dropped. Entries are keyed by date plus artists and merged into a persistent calendar.

**C6. 🟡 How is the LLM response parsed, and what's fragile about it?**
> I ask for JSON only, then slice from the first `{` to the last `}` and `json.loads` it. If that fails, the summary is skipped and the email still sends. It's fragile if the model puts braces in prose or wraps the JSON in explanation. Tool use or a JSON schema would be more robust.

**C7. 🟢 How is HTML injection prevented in the email?**
> Every interpolated value, including headlines, sources and the AI output, goes through `html.escape`. There are about 44 call sites in the renderer. Treating LLM output as untrusted is important.

**C8. 🟡 How does the workflow avoid shell injection from the manual "hours" input?**
> It validates the input against `^[0-9]+$` in bash before passing it as an argument. Anything else falls back to the default run.

---

## (d) Underlying ML/CS theory

**D1. 🟡 Jaccard vs edit-distance vs embeddings for duplicate detection?**
> Jaccard on tokens is order-insensitive and cheap, but blind to synonyms. Edit-distance or SequenceMatcher is order-aware and catches small rewordings, but it's slow, roughly quadratic per pair. Sentence embeddings with cosine similarity capture paraphrases, like "unveils LP" vs "drops new record", but cost compute and need threshold tuning. At scale you'd use MinHash/LSH for Jaccard candidates and embeddings for the final decision.

**D2. 🟡 What's the difference between leader clustering and agglomerative clustering?**
> Leader clustering makes one pass: each item joins the first cluster whose leader is similar enough, otherwise it starts a new one. It's O(n·k) but order-dependent. Agglomerative clustering repeatedly merges the closest pair under a linkage rule. It's deterministic, but O(n² log n). My approach is leader-style with an index to limit comparisons.

**D3. 🔴 How do you mitigate hallucination and prompt injection in the summary?**
> Grounding instructions ("only facts present above, never guess numbers or dates"), structured output, and escaping the output. What I'd add: wrap the headlines in delimiters with an instruction to treat them as data, validate that every extracted date literally appears in a cited headline, cap output length, and keep the AI section visually separate and labelled. Prompt injection can't be fully prevented, so the design limits its impact to text in an email.

**D4. 🟡 Why is outlet count a good importance signal?**
> Independent editorial decisions to cover an event are a noisy vote on its newsworthiness. More distinct outlets means more consensus. It's robust to any single outlet's bias and needs no training data. The failure mode is syndicated content inflating counts.

**D5. 🟢 What's an inverted index?**
> A map from each term to the list of documents containing it. It's the core data structure of search engines. Here it maps title tokens to candidate stories.

**D6. 🟡 How would you turn section routing into a learned classifier?**
> Label a few hundred stories with their correct section, train a multi-label classifier (logistic regression on TF-IDF, or a small fine-tuned transformer), keep the keyword hits as features, and pick the top label with a confidence threshold, falling back to the rules when unsure. Evaluate with per-section precision and recall.

---

## (e) Evaluation & metrics

**E1. 🔴 How do you know the clustering is good?**
> Honestly, only by eye today. There are no labels or tests. To measure it: take one day's raw items, hand-group them into true stories, and compute pairwise precision and recall, or B-cubed F1, of my clustering. Then sweep the Jaccard and ratio thresholds and pick the best F1. I'd also track the distribution of cluster sizes over time as a drift signal.

**E2. 🟡 What metrics would you track in production?**
> Source health (it already shows failed or stale feeds in the footer), items per day, stories per day, the share of items placed in "More headlines" (a proxy for routing gaps), AI success rate and token cost, and email size versus the clipping limit.

**E3. 🟡 How would you evaluate the release calendar?**
> Precision: sample extracted dates and check they're real release dates for the named artist. Recall: compare against a known release schedule for a week. Also report the AI-sourced vs regex-sourced split.

**E4. 🟢 How would you evaluate the AI summary?**
> Faithfulness: every claim in a bullet should trace to a headline, which you can check with a second LLM or by hand. Usefulness: is it read or clicked? Plus format-failure rate and cost.

---

## (f) Scaling, production & system design

**F1. 🔴 What are the reliability semantics of a daily run?**
> At-least-once. State is saved only after the email succeeds, so a failure means tomorrow's run re-includes today's content rather than losing it. The flaw is that there are two emails. If the first sends and the second fails, the first is duplicated next time. Recording each email's success separately would fix that.

**F2. 🟡 How would you handle a chart site redesign?**
> Today the parser raises, the chart is marked failed in the footer, and the rest of the digest still sends, which is graceful degradation. I'd add golden-file tests with saved HTML, an alert when a chart fails two days running, and parser selectors in config.

**F3. 🟡 What limits throughput?**
> Politeness gaps on Google News (1.2 s per request across about 45 searches including artist batches) dominate. RSS feeds run 10 in parallel. The whole run fits inside the 25-minute job limit. The README says a run takes a minute or two locally.

**F4. 🟢 How is cost controlled for the LLM?**
> A cheap model, a headline budget (160 headlines, spread evenly across sections), `max_tokens 2000`, and it's opt-in: no API key, no call. I'd log real token usage to verify the README's two-to-three-cents-a-day estimate.

---

## (g) Failure modes & debugging

**G1. 🔴 The same story appears twice in "Superstars". How do you debug it?**
> Print both items' normalised token sets. Likely causes: they share fewer than two non-generic tokens because of a paraphrase, or the second item was compared against a different seed story first and matched there. Fixes: add synonyms or lower thresholds (measured on labels), compare against all cluster members, or add embedding similarity.

**G2. 🟡 A recurring column ("New Music Friday") stopped appearing. Why?**
> Seen IDs include a hash of the normalised title. If the headline is identical week to week, the new article is treated as already seen for 10 days. Use URL plus (title, source) instead of title alone.

**G3. 🟡 The calendar shows a wrong date for an album. Why?**
> Either the regex matched a date in an unrelated clause, the year heuristic shifted it, or the AI extracted it without a supporting headline. Calendar entries record their source ("AI summary" vs an outlet), so check that first.

**G4. 🟡 Emails land in Promotions or get clipped. What do you do?**
> Clipping: Gmail clips HTML over about 100 KB, which is why `fit()` renders progressively shorter levels until the HTML is under a 95 KB budget (`max_email_kb`, default 95). Promotions: sender reputation. Moving it once trains Gmail. Plain-text alternative parts help too.

**G5. 🟢 A feed returns 402. What does that mean?**
> The site's bot paywall (TollBit) asks bots to pay. The code labels it "asks bots to pay". For Billboard, Rolling Stone and Variety I use Google News headlines instead of scraping them.

---

## (h) "Why didn't you…" / alternatives

**H1. 🟡 Why not use embeddings for clustering?**
> Zero-dependency and free on GitHub runners was the constraint, and lexical matching worked well enough for headline-level duplicates. Embeddings are the obvious upgrade for paraphrases. A small model like MiniLM runs fine on CPU for about a thousand titles.

**H2. 🟡 Why not a newsletter service like Substack or Mailchimp?**
> It's a personal digest generated fresh daily. Gmail SMTP with an app password is free and simple. For multiple recipients at scale I'd use SES or SendGrid for deliverability and unsubscribe handling.

**H3. 🟢 Why not the official Anthropic SDK?**
> Raw `requests` kept dependencies minimal, and one call didn't need streaming or tools. The SDK would add retries, typed responses and usage reporting, which I'd now want.

**H4. 🟡 Why scrape kworb and Official Charts instead of APIs?**
> Spotify and Billboard chart tables aren't available as free APIs. Kworb aggregates them, and Official Charts publishes the Hot 100 and Billboard 200 under licence. It's fragile and I respect rate limits, but a licensed data provider would be the production answer.

**H5. 🟡 Why rules for routing instead of an LLM classifying every story?**
> Cost, latency, determinism and debuggability. Rules are editable in YAML by a non-programmer. An LLM would be better on ambiguous stories, so I'd use it selectively on stories that end up in "More headlines".

---

## (i) Behavioural (STAR)

**I1. 🟡 Tell me about designing for a non-technical user.**
> **S:** The user was an artist, not a developer. **T:** Make setup and customisation possible without coding. **A:** Everything configurable lives in a commented `config.yaml` that's editable on GitHub's web UI. The README walks through Gmail app passwords and GitHub secrets click by click. Error messages are plain English ("website said 403 (blocked)"), and the email footer lists broken sources. **R:** It runs unattended daily, and changes are YAML edits.

**I2. 🟡 Tell me about handling an external constraint.**
> **S:** Billboard, Rolling Stone and Variety put automated readers behind a paywall. **T:** Still cover them. **A:** I switched to their headlines through Google News, and got the Hot 100 and Billboard 200 tables from the UK Official Charts site, which publishes them. **R:** Coverage without fighting a bot wall. Global charts that weren't available became "chart headlines" instead.

**I3. 🟡 Tell me about a reliability decision.**
> I made the run at-least-once: memory is saved only after the email is sent, so a failed send never silently drops a day's news. Later I noticed the two-email edge case causes duplicates, and the fix is per-email state.

**I4. 🟢 How did you decide what to build first?**
> News clustering and routing first, because that's the daily value. Then charts. Then the calendar, which builds on both. Then the AI summary as an optional layer that can fail without breaking anything.

---

## Hostile follow-ups

**X1. 🔴 "No tests at all for 2,000 lines of parsing and clustering. How do you know it works?"**
> Daily operation and reading the output, which isn't enough. HTML parsers and regexes are exactly the code that breaks silently. Golden-file tests with saved feeds and chart pages are my top improvement.

**X2. 🔴 "Your similarity thresholds are magic numbers."**
> They are, chosen by inspecting real duplicates. The right process is to label one day's clusters and tune for pairwise F1. Until then I can only say they work on what I've eyeballed.

**X3. 🔴 "You feed arbitrary internet text into an LLM prompt. That's a prompt injection vector."**
> Yes. The mitigations are that output is only shown as escaped text in an email, there are no tools or actions, and the prompt asks for grounded JSON. I'd add data delimiters and validate every date the model extracts against source text. The blast radius is a misleading sentence, not an action.

**X4. 🟡 "Committing a 13,000-line JSON file daily: isn't that abusing git?"**
> It's a free persistence hack for a personal tool. It bloats history. For anything bigger I'd use the Actions cache with a fallback, or a tiny hosted KV store.

**X5. 🟡 "Is scraping kworb and Official Charts allowed?"**
> I use an honest User-Agent, per-host rate limits, and avoid sites that ask bots to pay. The README claims Official Charts permits this kind of reading, but I haven't verified their terms in detail. A product would need licensed data.

**X6. 🟡 "Where's the ML?"**
> Clustering and IR, regex information extraction and an LLM integration. No trained model. The ML extensions are clear: embedding-based clustering, a learned section classifier, and learning-to-rank if click data existed.

**X7. 🟡 "README says about 75 sources. Can you back that up?"**
> Config has 26 enabled RSS feeds and 22 Google News searches, plus batched artist searches (222 superstars, 10 per query). Whether that's "about 75" depends on what you count as a source. I'd quote the config numbers.

**X8. 🟡 "What if two runs overlap and both commit state?"**
> The workflow has a concurrency group without cancellation, so runs queue rather than overlap. And the commit step does `pull --rebase` before pushing.
