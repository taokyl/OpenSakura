# discord/ — Discord mode (not yet available)

The Discord bot has not been ported to OpenSakura yet. What exists today:

- the **Chat in Discord** switch and the `discord` settings block in Setup
- the endpoints a bot will use: `POST /reply` (one turn in, one reply out) and `POST /discord/state`
- the reply toggles marked "(Discord mode, coming soon)" in Setup

Selecting Discord mode currently only disables the Play tab. Planned: text replies in channels with
`all` / `mention` / `smart` triggers, then voice through the TTS and STT services. Scope is still
being decided; contributions welcome.
