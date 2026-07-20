# Wingman on your phone

Two honest facts first:

- **There is no app-store app and no APK.** Wingman on your phone is the
  same web app, pinned to your home screen. That's deliberate — one
  codebase, nothing to sideload, your data stays on your computer.
- Your phone talks to **your computer**, so the computer must be on and
  running Wingman, and the phone must be able to reach it (same Wi-Fi,
  or Tailscale from anywhere).

## Step 1 — let the phone reach Wingman

Out of the box Wingman only listens to the computer it runs on
(`127.0.0.1`). Pick one of these:

### Option A: same Wi-Fi (simplest)

1. On the computer, find its address on your home network:
   - Linux: `hostname -I` (first number, like `192.168.1.23`)
   - Windows: `ipconfig` → "IPv4 Address"
   - Mac: System Settings → Wi-Fi → Details
2. Tell Wingman to accept your phone: edit `~/.config/wingman/env`
   (create it if missing — on Windows the file is
   `C:\Users\you\.config\wingman\env`) and add:

   ```
   WINGMAN_HOST=0.0.0.0
   ```

   Restart Wingman (`systemctl --user restart wingman`, or Ctrl+C and
   start it again).
3. On the phone's browser, open `http://<that address>:8484`, e.g.
   `http://192.168.1.23:8484`.

Only devices on your home Wi-Fi can reach it. Away from home it won't
load — that's what Option B fixes.

### Option B: Tailscale (works from anywhere, still private)

[Tailscale](https://tailscale.com) (free for personal use) puts your
computer and phone on a private network of their own — no ports opened
to the internet, nothing public.

1. On the computer: install Tailscale
   (`curl -fsSL https://tailscale.com/install.sh | sh` on Linux, or the
   normal installer on Windows/Mac), then `sudo tailscale up` and log in
   (Google/GitHub/etc.).
2. On the phone: install the **Tailscale** app, log in with the same
   account, and flip it on.
3. Set `WINGMAN_HOST=0.0.0.0` as in Option A and restart Wingman.
4. In the Tailscale app (or `tailscale status` on the computer), find
   the computer's Tailscale name or 100.x.y.z address, and open
   `http://<tailscale-name>:8484` on the phone. Works from anywhere.

## Step 2 — pin it to your home screen

On the phone, with the Wingman page open in Chrome:
**⋮ menu → Add to Home screen** (or "Install app"). Wingman now opens
full-screen from its own icon like any app.

Bonus once installed: in any job app or browser page, **Share →
Wingman** sends the link straight into Wingman's capture page — this is
the supported way to track LinkedIn/Indeed jobs.

## Step 3 — push notifications (morning digest + reminders)

1. Install the **ntfy** app
   ([Play Store](https://play.google.com/store/apps/details?id=io.heckel.ntfy)).
2. In ntfy: **+ → Subscribe to topic** and invent a topic name nobody
   would guess, e.g. `andy-wingman-x7k2p9`. The topic name works like a
   password — anyone who knows it can read the notifications, so make it
   long and random.
3. In Wingman: **Notify** page → enter the same topic → Save → **Send a
   test push**. Your phone should buzz.

Every morning you'll get "N new matches, M follow-ups due" with the top
picks; due reminders arrive as they come due. Wingman never notifies
anyone but you.
