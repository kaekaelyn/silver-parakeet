# Running Wingman on your computer

This guide assumes nothing. If a step doesn't look like what's on your
screen, stop and ask — don't guess.

Wingman runs on **your own computer** and shows its screen in your web
browser. Nothing is uploaded anywhere; closing the program stops it.

## What you need (all free)

1. **The Wingman folder** — download it from the GitHub page (green
   **Code** button → **Download ZIP**, then unzip it somewhere you can
   find, like your Desktop), or `git clone` it if you know git.
2. **uv** — a small helper that installs everything else Wingman needs.
   One command, below.

## Linux (the intended home)

Open a terminal in the Wingman folder and run:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh   # install uv (once)
./install.sh
```

The installer sets everything up and starts Wingman as a background
service that comes back after reboots. When it finishes, open
<http://127.0.0.1:8484> in your browser. That's it.

Useful afterwards:

- `systemctl --user status wingman` — is it running?
- `systemctl --user restart wingman` — restart it
- `uv run wingman backup` — write a backup file of everything to your
  home folder
- `uv run wingman restore <backup file>` — put a backup's data back
  (add `--force` to replace what's there now; Wingman saves a safety
  copy of the current data first)

## Windows

There's no installer service on Windows — you run Wingman in a window
and it works while that window is open (this is "dev mode"; it's fine
for daily use).

1. Install uv: open **PowerShell** (press the Windows key, type
   `powershell`, press Enter) and paste:

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   Close PowerShell and open a new one so it notices uv.

2. In PowerShell, go into the Wingman folder (if it's on your Desktop):

   ```powershell
   cd $HOME\Desktop\wingman
   ```

3. Start Wingman:

   ```powershell
   uv run wingman serve
   ```

   The first start downloads what it needs and takes a few minutes;
   after that it starts in seconds. Leave this window open.

4. Open <http://127.0.0.1:8484> in your browser.

To stop Wingman: close the PowerShell window (or press Ctrl+C in it).
To start it again: steps 2–4.

One-time extra for the apply engine (the browser Wingman drives to fill
application forms):

```powershell
uv run playwright install chromium
```

## Mac

Same idea as Windows, in the **Terminal** app (find it with Spotlight,
⌘-space, type "terminal"):

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh    # once
cd ~/Desktop/wingman                                # or wherever you put it
uv run wingman serve
```

Open <http://127.0.0.1:8484>. Leave the Terminal window open while you
use Wingman; close it (or Ctrl+C) to stop. The apply engine needs the
same one-time `uv run playwright install chromium` as Windows.

## First five minutes inside the app

1. **Sources** — the built-in job boards are already on. Add companies
   you'd love to work for under "Watch a company".
2. **Criteria** — tell Wingman what a good job looks like for you.
3. **Vault** — your contact details, resume, and canned answers. This is
   what the apply engine fills forms from.
4. **Notify** — optional: push notifications to your phone
   (see [PHONE.md](PHONE.md)).
5. Come back to the **Inbox** — ranked matches appear within a couple of
   minutes of the first fetch.

## Updating Wingman

Your jobs, criteria, and vault live in a separate data folder, so
updating the program never touches them. Still, one command of insurance
first:

```sh
uv run wingman backup
```

That writes a `wingman-backup-….tar.gz` file to your home folder. (If
you ever need it: `uv run wingman restore <that file>` puts everything
back.)

Then get the new version:

- **If you used git:** in the Wingman folder, run `git pull`.
- **If you downloaded a ZIP:** download the new ZIP from the same GitHub
  page and unzip it over your Wingman folder (replace the files — your
  data is not in this folder).

And restart:

- **Linux (installed as a service):** re-run `./install.sh` — it's safe
  to run again and picks up anything new the update needs. (Or just
  `systemctl --user restart wingman` for a small update.)
- **Windows / Mac (dev mode):** stop Wingman (Ctrl+C or close the
  window) and start it again with `uv run wingman serve`.

Any database changes a new version needs are applied automatically the
next time Wingman starts — there is no separate upgrade step.

## Something's wrong?

- **The page won't load** — is the terminal window still open and free of
  red text? Start it again with `uv run wingman serve`.
- **`uv` is "not recognized"** — open a fresh terminal window; if it
  still isn't, redo the uv install step.
- **A job board shows an error on the Sources page** — that board is
  having a bad day; the others keep working. Errors show in the
  "Last error" column and clear on the next successful fetch.
