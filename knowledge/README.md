# Shared agent knowledge

Maintain these source files:

- `COMPANY.md` — company, product descriptions, order process, delivery, warranty and contacts.
- `PRICING.md` — starting prices, currency, sources, verification date and pricing limitations.
- `COMMUNICATION.md` — identity, conversation style, consultation, authority and human handoff.
- `DROPBOX_GUIDE.md` — full company photo-tag and folder guide, including expanded sections and text descriptions of its two screenshots. Source snapshot dated 2026-11-12; refresh it explicitly when the published guide changes. `dropbox-guide-assets/` preserves the original screenshots.

After editing them on the VPS, run from `/root/projects/esteem`:

```sh
python3 ops/build_identity.py --reload
```

This rebuilds `AGENT.md` atomically and restarts the WhatsApp gateway. Telegram and MAX read the rebuilt file on their next generation. Editing a source file alone does not refresh the runtime bundle. All channels receive the same full context; this is not selective retrieval. Owner profiles and customer histories remain separate.

Verify consistency with `python3 ops/build_identity.py --check`. Do not edit generated `AGENT.md` directly. Research provenance stays in `PUBLIC_RESOURCES.md` and `SOURCE_INVENTORY.json`.

The full Dropbox guide is included in the generated identity, so Telegram, WhatsApp and MAX receive it directly; they do not need a browser or a filesystem tool to use it. The guide does not widen the photo connector beyond `/Products Esteem`. Source-only material in `sources/` is archived for provenance, not automatically loaded into the agent. The 2026-11-12 mats notes are distilled into `COMPANY.md`, with conflicting layer descriptions left unconfirmed.

WhatsApp has `context_file_max_chars: 65536` in its private config so the complete shared identity is retained even when model context size is unavailable. Recheck effective prompt loading if the bundle grows beyond this limit.
