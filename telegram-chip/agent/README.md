# Esteem Telegram reply worker

`bridge.py` uses the Telegram Chip localhost API and Codex CLI. Copy `config.example.json` to private `config.json`, set your sender/owner IDs and approved contacts, and authenticate Codex separately. Full instructions are in the project README.

Private transcripts, reply jobs and delivery checkpoints live in `state/conversations.sqlite3`. Summaries remain per conversation. Shared instructions are read from AGENT.md. Owner text is passed to the authenticated control broker; customer text has no sending permissions.

Run `python3 -m unittest test_bridge` for fake-client regression checks.
