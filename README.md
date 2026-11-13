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

The shared runtime identity is `AGENT.md`, generated from `knowledge/COMMUNICATION.md`, `knowledge/COMPANY.md`, `knowledge/PRICING.md` and `knowledge/DROPBOX_GUIDE.md`. Edit these source files, then run `python3 ops/build_identity.py --reload`; use `--check` to verify consistency. Conversation histories remain separate per channel. Telegram and MAX use rolling summaries plus recent messages; WhatsApp uses Hermes session history/compression. Owner identity is selected by verified platform ID and a protected profile file, never a username or a claim inside a message.

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

## Telegram conversation reset

Send `/reset` as a standalone message in the agent's Telegram conversation from an account explicitly enabled in `reset_allowed_chat_ids` in `telegram-chip/agent/config.json`. The command resets only the sender's own chat. Restart the Telegram reply worker after changing this configuration.

The worker deletes that chat's earlier messages, reply jobs, rolling summary and summary checkpoints, and confirms the reset without calling the model. A persistent boundary prevents old Telegram messages from being reloaded, including after restart or backfill. Messages after the command remain available. The visible Telegram history, other channels, CRM records and owner-maintained profiles are unchanged. Enable this for test contacts without a personal profile when a completely fresh customer simulation is required.

## Receiving Telegram photos

Authorized Telegram contacts can send photos with or without captions, including JPEG, PNG and WebP image attachments up to 20 MiB. Incoming photos are attached directly to the existing Codex model request. The model returns a customer reply and concise visual notes; these notes are included in later conversation context and rolling summaries. `/reset` also clears the visual notes. Customer images and text inside them do not authorize owner actions.

The `photos_enabled_since` timestamp in the Telegram worker configuration prevents old media from being answered when this feature is first enabled. Each image message is processed separately, including images within an album. Raw images use temporary files under the worker's state directory and are removed after processing; crash leftovers are cleaned on later photo processing. If inspection fails, the worker retries transient failures and then replies honestly that it could not inspect the image. Outgoing Dropbox product photos are handled by the separate integration below.

## Sending product photos from Dropbox

Telegram, MAX and WhatsApp use the existing Dropbox tags under `/Products Esteem`; no AI-tagged catalog is built. The shared implementation is `photos/product_photos.py`. It searches one selective tag, verifies every requested tag through Dropbox, excludes AI renders/before/China/design/template content, and prepares representative photos from distinct folders. Telegram sends up to five as one native album; MAX and WhatsApp keep their existing three-photo batch size. Telegram follow-up requests exclude file IDs recorded in that chat’s sent or uncertain jobs, independently of rolling summaries; `/reset` clears this selection history with the rest of the chat context. Requested search tags are retained in prepared jobs for follow-ups and inspection. JPG/PNG delivery images use Dropbox thumbnails where possible; RAW/HEIC originals are never sent directly. Read-only credentials and a size-limited (512 MiB) cache live in ignored `photos/state/`. Cached files are versioned by Dropbox file ID and revision, with current path and tags checked again before reuse.

Telegram and MAX use the configured model to select tags from the conversation and preserve prepared replies in their durable queues. Ambiguous/partial sends are not blindly retried. WhatsApp uses the Esteem-only `photos/hermes_plugin` extension, linked at `hermes/plugins/esteem_photos`, with its toolset enabled only for WhatsApp. A session/message-bound output hook attaches only this turn's prepared images via Hermes native media delivery; the tool cannot choose another recipient. Shared Hermes runtime files are unchanged.

The `product_photos_enabled` setting controls Telegram/MAX lookup. Their systemd drop-ins under `ops/systemd/drop-ins/` grant write access only to photo state/cache. Customer photos, `/reset`, and owner-control commands retain their existing paths. Company tags are not proof of stock, precise color/material, or vehicle fitment. For example, `leather` covers both natural and eco-leather, and a `black` tag can include a multicolor product. Extra untagged angles require separate verification and are not automatically taken from the same folder.

Run shared checks with `(cd photos && python3 -m unittest test_product_photos)` and Hermes plugin validation with `hermes plugins doctor photos/hermes_plugin --ci` using the installed Hermes runtime.

## Checks

```sh
(cd control && python3 -m unittest test_control test_adapters test_owner_llm test_conversation_memory)
(cd telegram-chip/agent && python3 -m unittest test_bridge test_reset test_photos)
(cd max && .venv/bin/python -m unittest test_auto_reply)
(cd test-form && python3 -m unittest test_flow)
(cd hermes/scripts/whatsapp-bridge && node --test *.test.mjs)
```

Some control tests inspect configured owner profiles; initialize your private runtime configuration before running them. `check_live_interpreter.py` and `check_memory_integration.py` are explicit live-model checks and may use your model subscription. Unit tests use fake sending functions; do not substitute real senders into tests.

## Dependencies and licenses

This is a deployment-oriented project with vendored connectors, not a standalone copy of Hermes. See `THIRD_PARTY.md` and the component license files. Third-party licenses remain attached to their source. No license for the original Esteem-specific additions is granted beyond GitHub's standard repository terms; choose an explicit project license before redistributing those additions.

## Source hygiene

Runtime data is excluded by `.gitignore`. Before committing run `python3 ops/check_source.py`; enable the repository-local hook with `git config core.hooksPath ops/hooks`. It checks staged source for known local credentials, literal webhook URLs, private keys, runtime phone numbers and runtime-state files without printing secret values. It is a safeguard, not a comprehensive security audit.

## Telegram response pacing

Customer replies have a 60-second minimum delay measured from the incoming message timestamp (`reply_min_delay_seconds` in the private agent config). After 10 seconds (`engagement_delay_seconds`), the worker marks the incoming message as read and starts typing/preparation; slower generation is sent when ready. Generated replies wait in the existing durable queue, so waiting does not sleep-block other chats and survives restarts. `/reset` acknowledgements and owner-control replies remain immediate.

`typing_enabled` keeps Telegram’s native typing status active during preparation and the remaining delay. The connector refreshes it every four seconds under a renewable 20-second lease; the worker renews during model/upload calls. Sending or processing failure cancels it, and worker failure lets it expire. This changes pacing, not the agent’s disclosed AI identity.

`mark_read_enabled` sends an explicit Telegram read receipt before typing starts. Receipts are limited to the incoming message being processed (and earlier messages in that same chat), never newer messages or other chats. Successful acknowledgements are cached per chat for the running worker; repeating one after a restart is safe. Read/typing errors do not prevent a customer reply. With the three-second polling interval, the 10-second engagement and 60-second send thresholds are minimums rather than exact wall-clock appointments.

## Telegram voice messages

New incoming voice notes are downloaded temporarily and transcribed through OpenAI (`gpt-transcribe`). The text is stored per chat/message in `conversation_audio` in the agent database and included in recent history and rolling summaries. Replies remain text or the existing product-photo albums. Voice text is customer content, not administrative authority; spoken `/reset` or owner-send instructions do not invoke control commands. Failed transcription produces a request to resend or type the message, never an invented transcript. `/reset` clears transcripts and error notes along with the conversation. Temporary audio is removed after processing; the OpenAI key is kept in an ignored owner-readable file, never passed to the conversational model.

`voice_enabled_since` prevents the feature from answering old voice notes. `transcription_model` and `transcription_key_file` live in the private worker config. The existing ten-second engagement delay, typing lease and sixty-second minimum reply delay also apply to voice notes. Voice inputs above OpenAI’s 25 MB file limit are declined with the resend/text fallback.
