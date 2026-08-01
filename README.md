# PiKaraoke (personal fork)

> **Disclaimer:** My background is in infrastructure, platform, and networking, not development. Every change in this fork was written, tested, and implemented with [Claude Code](https://claude.com/claude-code).

<img width="588" height="339" alt="Image" src="https://i.ibb.co/Z6MTM4wt/pikaraoke-readme.png" />

This is a personal fork of [vicwomg/pikaraoke](https://github.com/vicwomg/pikaraoke) — all credit for the original project goes to its creator and contributors. My friends and I have spent more late nights than we can count singing on this thing, and over time it's grown a pile of custom features built for how we actually use it at our parties. Sharing them here in case they're useful to anyone else running PiKaraoke for their own crew.

None of this exists without the original project, so if it's made your parties better too, consider [buying the original creator a coffee](https://www.buymeacoffee.com/vicwomg).

## Custom features & improvements

- **Public player controls** — Play, pause, transpose, and volume no longer require the admin password, so anyone at the party can help run the show. Skip stays admin-only, since letting anyone cut off a performer felt like a step too far.
- **Color themes** — Four selectable themes: Dark "Neon Tiki", Light "Daylight Lounge", Sage "Cozy Whiskers" (a dark teal, cat-inspired palette), and a "Classic" option that restores the original look. Switchable from the admin panel with a custom font.
- **Custom logo upload** — Admins can upload their own logo image right from the admin panel, no file editing required.
- **Lifetime song stats** — PiKaraoke now remembers how many times every song has ever been played, viewable sorted by popularity in the Library page (formerly "Browse"), which also spotlights the 3 most-played songs up top for quick access.
- **Tonight's Recap** — A live page showing the current (or most recent) karaoke session: total songs sung, who showed up, an MVP singer, the most-played songs, and a click-to-expand list of exactly what each singer sang. Admins can name sessions (e.g. "John's Birthday") and browse a full history of past sessions from the admin panel.
- **Active Singers sidebar** — See at a glance who currently has a song queued up, including whoever's performing right now.
- **Per-user queue limit** — Defaults to 5 songs per person (including whatever's currently playing), so one enthusiastic guest can't monopolize the whole night. Adjustable by admins.
- **Audit log** — The admin panel logs who queued, paused, skipped, transposed, changed volume, or downloaded a song, so it's easy to see what's been happening.
- **Friendlier bot protection** — An invisible trap link and a simple "you need to give a name" requirement keep bots from spamming the queue, without resorting to CAPTCHAs or IP-based rate limits (which would unfairly penalize a room full of guests sharing one WiFi network).
- **Site-wide name prompt** — Everyone's asked for a display name on their first visit to any page, not just when searching, so the audit log and recap stats aren't full of "Anonymous."

## Docker Compose

This repo ships a bare-bones [docker-compose.yml](docker-compose.yml) that pulls this fork's prebuilt image instead of building from source:

```sh
docker compose up -d
```

Before running it:

- Edit `command:` and replace `<YOUR_LAN_IP>` with your machine's local network IP (e.g. `http://192.168.1.50:5555`) — the `-u` flag is what gets baked into the QR code guests scan.
- The `-d /app/pikaraoke-songs` flag tells PiKaraoke where to find/store your song library inside the container — keep it matching the container-side path in the `volumes:` mount below if you change that path.
- PiKaraoke listens on port 5555 by default, so you don't need to touch anything just to use that port. To use a different port instead, add `-p [port]` to `command:` and update the `5555:5555` mapping to match.
- Edit the `TZ` environment variable to your local timezone (e.g. `America/Chicago`) so timestamps in the Admin panel and Recap page show up in local time instead of UTC.
- The two `volumes:` bind mounts (`~/pikaraoke-songs`, `~/.pikaraoke`) persist your song library and settings/database across container restarts — change the left-hand paths if you'd rather store them somewhere else.

See the [official PiKaraoke wiki](https://github.com/vicwomg/pikaraoke/wiki/) for the full list of command-line flags and what they do.

## Everything else

For installation, usage, Docker instructions, and all the original PiKaraoke documentation, see **[docs/README.md](docs/README.md)**.
