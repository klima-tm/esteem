# Esteem

Experimental AI sales agent for website inquiries, with Telegram personal-account messaging, WhatsApp through Hermes/Baileys, MAX, and a separate Bitrix24 sandbox.

## Project map

| Directory | Purpose |
| --- | --- |
| `control/` | Verified-owner commands, multilingual LLM interpretation, profiles, first-contact tools and rolling conversation memory |
| `telegram-chip/` | Modified Telegram Chip API and the Telegram reply worker in `agent/` |
| `hermes/` | Hermes configuration template and the isolated WhatsApp bridge |
| `max/` | Vendored PyMax client, MAX connector and automatic reply worker |
| `bitrix/` | Host-pinned sandbox CRM client and setup helpers |
| `test-form/` | Standalone inquiry form, durable workflow and channel fallback |
| `ops/` | Systemd service definitions and dependency compatibility patch |
| `profiles/` | Manually maintained contact profile templates |

The shared identity lives in `AGENT.md`. Conversation histories remain separate per channel. Telegram and MAX use rolling summaries plus recent messages; WhatsApp uses Hermes session history/compression. Owner identity is selected by verified platform ID and a protected profile file, never a username or a claim inside a message.

## Runtime and configuration

The current deployment uses Linux, Python 3.12 for project workers, Node.js for the WhatsApp bridge, and a separately installed Hermes runtime at `/usr/local/lib/hermes-agent-production`. Services and source currently expect the project at `/root/projects/esteem`; relocate those paths explicitly for another deployment.

1. Create Python environments for `telegram-chip` and `max`; install the dependencies from their manifests. MAX uses the local package: `.venv/bin/pip install -e .`. The form, controls and CRM client use Python's standard library except when importing the Telegram/FastAPI endpoint.
2. Install the external Hermes runtime documented in `THIRD_PARTY.md` and authenticate your chosen model provider yourself. Existing workers use the Codex CLI subscription login; no model credential is supplied in this repository.
3. In `hermes/scripts/whatsapp-bridge`, run `npm ci`, then apply `ops/patch_baileys_pairing.py --bridge /root/projects/esteem/hermes/scripts/whatsapp-bridge` for the pinned Baileys compatibility changes.
4. Copy the `*.example.*` and `.env.example` files to the corresponding runtime filenames and set your own account IDs, allowed contacts, paths and credentials. Configure the Telegram owner ID in `telegram-chip/agent/config.json` and create its matching `profiles/telegram/ID.json`. Runtime credentials, profiles, histories and contact configuration are intentionally ignored by Git.
5. Authenticate Telegram, WhatsApp and MAX interactively with accounts you control. Never run two bridges against the same linked-device session. MAX's manual connector must not run alongside its automatic reply service.
6. Create a separate Bitrix24 test portal. The sandbox hostname is deliberately pinned in `bitrix/sandbox_client.py`; configure it for your own **non-production** portal. Store its webhook URL only in `bitrix/sandbox.env`. Review `bitrix/setup_sandbox.py` before using it: it creates custom deal fields.
7. For the form, install `cloudflared` from Cloudflare's official release, place it at `test-form/bin/cloudflared`, and generate `test-form/access-token` with `secrets.token_urlsafe(32)`. `esteem-test-form-tunnel.service` supplies a temporary HTTPS hostname; append `/t/` plus that token. The hostname can change on tunnel restart. Keep the resulting capability link private to testers.
8. Review `ops/systemd/`, copy the required units into `/etc/systemd/system`, reload systemd, and start only the services you have configured. Do not enable messaging before reviewing account ownership and authorized recipients.

The repository does not install credentials, automatically create live profiles, or run outreach on clone. It does not contain the production CRM credential. Local-only deployment notes, when present, are in ignored `OPERATIONS.local.md`.

## Form workflow

A submission gets a UUID and is written to `test-form/submissions.sqlite3`. The workflow creates a deal only in the configured sandbox, verifies the source/UUID/phone, generates an opening message, and tries Telegram → WhatsApp → MAX. Only a definitive unavailable/rejected result permits fallback. A timeout or an ambiguous send stops for review. Reusing the same submission ID never intentionally sends a second message. A CRM status-update failure after a successful send does not repeat the send.

`test-form/submissions.sqlite3` stores `jobs` and `attempts`. It is not tracked. The form shows the opening text, channel results and a link to its sandbox deal. Subsequent customer replies are handled by the channel agents; the full subsequent chat is not mirrored into the CRM timeline yet.

Owner commands accept explicit `/contact CHANNEL +PHONE MESSAGE` or natural text through the Telegram owner conversation. These commands currently select a single channel; the form owns automatic channel fallback. Contact allowlists can be expanded by owner-authorized first-contact requests. There is no project-wide hardcoded test-number barrier: account operators must use approved test recipients.

## Checks

```sh
(cd control && python3 -m unittest test_control test_adapters test_owner_llm test_conversation_memory)
(cd telegram-chip/agent && python3 -m unittest test_bridge)
(cd max && .venv/bin/python -m unittest test_auto_reply)
(cd test-form && python3 -m unittest test_flow)
(cd hermes/scripts/whatsapp-bridge && node --test *.test.mjs)
```

Some control tests inspect configured owner profiles; initialize your private runtime configuration before running them. `check_live_interpreter.py` and `check_memory_integration.py` are explicit live-model checks and may use your model subscription. Unit tests use fake sending functions; do not substitute real senders into tests.

## Dependencies and licenses

This is a deployment-oriented project with vendored connectors, not a standalone copy of Hermes. See `THIRD_PARTY.md` and the component license files. Third-party licenses remain attached to their source. No license for the original Esteem-specific additions is granted beyond GitHub's standard repository terms; choose an explicit project license before redistributing those additions.

## Source hygiene

Runtime data is excluded by `.gitignore`. Before committing run `python3 ops/check_source.py`; enable the repository-local hook with `git config core.hooksPath ops/hooks`. It checks staged source for known local credentials, literal webhook URLs, private keys, runtime phone numbers and runtime-state files without printing secret values. It is a safeguard, not a comprehensive security audit.
