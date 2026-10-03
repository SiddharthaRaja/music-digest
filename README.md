# Music Digest

A script that reads about 75 music news sources and 16+ charts every day, merges duplicate coverage, sorts everything into detailed sections and emails you two digests you can read on your phone:

1. **News.** Everything that happened since your last digest, sorted by artist, topic, country and scene.
2. **Charts & Stats.** The number ones, full chart tables, who is where, breakouts and sales numbers.

Run it whenever you like, or let GitHub run it for free every morning at about 6 AM India time.

## What's in the News email

- **Number ones at a glance** in the header: Hot 100, Billboard 200, UK Singles and Albums, Spotify Global.
- **Today in 60 seconds** and **For your rollout** (optional AI summary, see below).
- **Release calendar.** Release dates mentioned anywhere in the news, built up day by day, with the busiest upcoming Fridays called out. Use it to keep your own release away from a crowded week.
- **Biggest stories.** Anything covered by 3 or more outlets.
- **Superstars.** Around 220 major artists across pop, hip-hop & R&B, country, rock, Latin, K-pop, Afrobeats, UK and electronic, grouped by artist.
- **Rising & breakthrough.** Rising artists, "artist to watch" coverage, plus **chart breakouts**: songs outside the superstar list that are new on a chart, jumping fast or being Shazamed.
- **Independent & DIY artists.** News about and for independent musicians, plus the UK Indie Singles Breakers chart.
- **The news by topic.** Release radar (announced), Out now, Charts & sales news, Awards, Tours & live, Legal & drama, Passings, Industry & business, Streaming/platforms/AI, Interviews & reviews.
- **By country.** USA and UK. Canada, Australia and India are ready to switch on.
- **Scenes.** Hip-hop & R&B, Underground & alternative, Electronic & dance, Rock & metal, Country & Americana, Latin, K-pop, Afrobeats.

Every story appears once, in its best-fitting section. Small tags show the other angles, like 🇬🇧, "Hip-hop & R&B" or "Out now". The email shows the best of each section. **Every story is in the attached full digest.**

## What's in the Charts & Stats email

- **Number ones right now** across every chart.
- **Who is where.** Each followed artist's best position on every chart.
- **Breakouts.** Rising songs and artists, with the evidence (for example "Spotify US #34 NEW · Shazam UK #8").
- **Sales, units & forecasts.** Figures quoted in the news (units, streams, copies), plus HITS Daily Double's first-week forecasts.
- **Billboard chart headlines** for the Global 200, Global Excl. US, Artist 100 and Emerging Artists.
- **Full chart tables**, with last-week movement, peak and weeks:
  - **United States:** Billboard Hot 100 and Billboard 200 (top 20), Spotify US, YouTube US, US radio airplay
  - **United Kingdom:** Official Singles and Albums (top 20), Spotify UK
  - **Independent artists:** UK Independent Singles and Albums, UK Indie Singles Breakers
  - **Scenes:** UK Hip Hop & R&B, UK Afrobeats (Dance and Rock & Metal are ready to switch on)
  - **Global:** Spotify daily and weekly, Apple Music worldwide songs and albums
  - **Discovery:** Shazam worldwide, US and UK. Shazam often spots hits before the other charts do.

Weekly charts are shown in full the day they update. On other days they shrink to a one-line reminder, so the email stays short.

### About Billboard

Billboard, Rolling Stone and Variety send automated readers to a paywall (TollBit) that charges bots for access, so this script doesn't read their sites directly. Here's how they're still covered:

- **Billboard Hot 100 and Billboard 200 tables:** from the UK's Official Charts site, which publishes them under licence and allows this kind of reading.
- **Billboard, Rolling Stone and Variety news:** their headlines come in through Google News.
- **Billboard Global 200, Global Excl. US, Artist 100 and Emerging Artists:** not available as tables. You get Billboard's weekly chart headlines instead.

---

## Part 1: Try it on your computer (about 10 minutes)

1. **Install Python** (version 3.10 or newer) from [python.org/downloads](https://www.python.org/downloads/).
   On Windows, tick **"Add python.exe to PATH"** on the first install screen.
2. **Open a terminal in this folder.**
   - Windows: open the folder, click the address bar, type `cmd`, press Enter.
   - Mac: right-click the folder → *New Terminal at Folder*.
3. **Install the helpers the script uses** (one time only):
   ```
   pip install -r requirements.txt
   ```
   (On a Mac, if `pip` isn't found, use `pip3`, and `python3` instead of `python` below.)
4. **See a preview** in your browser, without sending any email:
   ```
   python digest.py --preview
   ```
   It takes a minute or two, because it politely spaces out its requests to each website. Both digests open in your browser.

## Part 2: Get it by email

The script sends from your own Gmail. Google won't let scripts use your normal password, so you make an **app password**: a separate 16-letter password for just this script, which you can delete any time.

1. Turn on **2-Step Verification** for your Google account if it isn't already on (Google Account → Security).
2. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), type `Music Digest` as the name, click **Create**, and copy the 16 letters.
3. In this folder, make a copy of `.env.example` and name it `.env`. Open it and fill in:
   ```
   EMAIL_ADDRESS=yourname@gmail.com
   EMAIL_APP_PASSWORD=abcd efgh ijkl mnop
   ```
4. Run it:
   ```
   python digest.py
   ```
   Check your inbox: two emails arrive. From now on, each run shows only what's new since your last digest.

Handy extras:
- `python digest.py --hours 72`: everything from the last 3 days, even stories you've already seen.
- Every digest is also saved in the `output` folder as web pages.

## Part 3: Make it run by itself every morning (free)

GitHub, a free code-hosting site, can run the script on its own computers on a schedule, so yours can be off.

1. **Make an account** at [github.com](https://github.com) and click **New repository** (the + at the top right).
   Name it `music-digest`, choose **Private**, and click **Create repository**.
2. **Upload the files.** On the new repository page, click **uploading an existing file** and drag in everything from this folder **except `.env`** (it has your password) and the `output` folder. Click **Commit changes**.
   - The `.github` folder is hidden on a Mac (press **Cmd + Shift + .** in Finder to show it).
   - If it still doesn't upload, click **Add file → Create new file**, type `.github/workflows/daily-digest.yml` as the name (the slashes create the folders), paste in that file's contents, and commit.
3. **Add your email details as secrets** (GitHub keeps these hidden, even from you after saving):
   repository **Settings → Secrets and variables → Actions → New repository secret**. Add:

   | Name | Value |
   |---|---|
   | `EMAIL_ADDRESS` | your Gmail address |
   | `EMAIL_APP_PASSWORD` | the 16-letter app password |
   | `EMAIL_TO` | *(optional)* a different address to send to; separate several with commas |
   | `ANTHROPIC_API_KEY` | *(optional)* turns on the AI summary, see below |

4. **Test it now:** go to the **Actions** tab → **Daily music digest** → **Run workflow**. After two or three minutes you'll see a green tick and both emails arrive.

That's it. It now runs every day at about 6 AM India time. You can also trigger it any time from your phone: open the GitHub app → your repository → **Actions** → **Daily music digest** → **Run workflow**.

If a run ever fails, GitHub emails you, and the run's page shows what went wrong.

### Changing the time

Open `.github/workflows/daily-digest.yml` on GitHub (click it, then the pencil icon) and change the `cron` line. The times are in UTC, which is 5 hours 30 minutes behind India:

| You want it around (India time) | Use |
|---|---|
| 6 AM | `- cron: "20 0 * * *"` |
| 9 AM | `- cron: "20 3 * * *"` |
| 12 PM | `- cron: "20 6 * * *"` |
| 9 PM | `- cron: "20 15 * * *"` |

The `20` makes it start a few minutes early, because GitHub sometimes starts scheduled runs late. For two emails a day, add a second `- cron:` line under the first.

---

## Changing what it covers

Everything lives in **`config.yaml`**. Each part has notes explaining it, and you can edit it on GitHub directly (click the file, then the pencil icon). The change applies from the next run.

- **Artists:**
  - Edit the `superstars` and `rising` lists.
  - Put artists you're studying closely under `pinned` and they'll always sit at the very top.
- **Countries:** set `enabled: true` on Canada, Australia or India, or copy a block to add another country.
- **Scenes and topics:** each one is a list of trigger words. If stories land in the wrong place, add or remove words.
- **News sites:** add an RSS feed under `feeds`. Add `tags` to say what the site specialises in (for example `[uk, underground]`), so its stories count towards those sections.
- **Google News searches:** add one under `google_news → searches` to cover any site or topic. `site:example.com` limits a search to one website.
- **Charts:** switch charts on or off, change how many rows each shows (`top`), or add another Official Charts or kworb.net page.
- **One email instead of two:** set `separate_charts_email: false`.

## Optional: the AI summary

With an Anthropic API key, the News email gets these extras at the top:

- "Today in 60 seconds"
- a one-line read on each big section
- a takeaway for your own rollout
- extra dates for the release calendar

To turn it on:

1. Create an account at [console.anthropic.com](https://console.anthropic.com), add a little credit under Billing, and create an API key.
2. Add it as `ANTHROPIC_API_KEY` (as a GitHub secret, and/or in your `.env`).

It uses Claude Haiku 4.5, the cheapest Claude model. AI use is billed in *tokens* (word-pieces, roughly ¾ of a word each). One digest sends about 15,000 tokens, which comes to roughly two to three cents a day. Without a key, everything else works the same.

## Good to know

- **Some sources aren't included.** X, Instagram and TikTok block automated reading, so the script relies on outlets reporting what happens there. Social posts and ticket listings that show up in Google News are filtered out.
- **Feeds sometimes break or move.** The bottom of each email names any source that failed or stopped posting. Fix or remove it in `config.yaml`.
- **Sorting is automatic.** It works from keywords, so the odd story will land in a slightly wrong section. Tweak the trigger words when you notice a pattern.
- **Release calendar dates** come from wording like "out November 14", so double-check before planning around one.
- **Reddit is switched off by default** because it usually blocks GitHub's servers. It often works when you run the script on your own computer: set `enabled: true` on the Reddit lines.
- **Your computer and GitHub keep separate memories** of what you've already seen.
- **Keep the repository private.** GitHub pauses schedules on public repositories that go quiet for a long time.
- If the first emails land in Spam or Promotions, move them to your inbox once and Gmail will learn.

## What's in this folder

| File | What it is |
|---|---|
| `digest.py` | the script you run |
| `news.py` | collects news, merges duplicates and sorts stories into sections |
| `charts.py` | reads the charts and works out the stats |
| `render.py` | lays out the emails |
| `ai.py` | the optional AI summary |
| `util.py` | small shared helpers |
| `config.yaml` | your settings: artists, sites, searches, sections, countries, scenes, charts |
| `.github/workflows/daily-digest.yml` | the schedule GitHub follows |
| `.env.example` | template for your email details when running on your computer |
| `state/seen.json` | created automatically; remembers what you've been sent, chart weeks and the release calendar |
| `output/` | created automatically; saved copies of each digest |
