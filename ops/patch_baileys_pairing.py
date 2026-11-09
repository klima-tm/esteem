#!/usr/bin/env python3
"""Apply the pinned Baileys pairing and session compatibility patch.

It ports WhiskeySockets/Baileys PRs #2765 and #2749 onto the 7.0.0-rc13
package bundled by Hermes Agent 0.21.0. Pairing applies it to a temporary
bridge; production deployment also applies it to the profile bridge because
freshly linked sessions need the same behavior during normal reconnection.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


BAILEYS_VERSION = "7.0.0-rc13"
PR_2765_COMMIT = "4f263f0e365c2e74dd1b824031d1c5910f518c26"
PR_2749_COMMIT = "38686677889a4db5356da51aa9517eb12c1e0866"


class PatchError(RuntimeError):
    """Raised when the installed package is not the reviewed patch target."""


def bridge_is_patched(bridge: Path) -> bool:
    base = bridge / "node_modules/@whiskeysockets/baileys"
    try:
        version = json.loads((base / "package.json").read_text())["version"]
        socket = (base / "lib/Socket/socket.js").read_text()
        utility = (base / "lib/Utils/companion-reg-client-utils.js").read_text()
        messages = (base / "lib/Socket/messages-recv.js").read_text()
    except (OSError, KeyError, json.JSONDecodeError):
        return False
    return bool(
        version == BAILEYS_VERSION
        and "handleCompanionRegRefresh" in socket
        and "makePairingQRRenderer" in socket
        and "pair-device-rotate-qr" in utility
        and "authState.creds.me?.id" in messages
    )


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise PatchError(f"Expected exactly one unpatched {label}; found {count}")
    return text.replace(old, new, 1)


def patch_bridge(bridge: Path) -> bool:
    package = bridge / "node_modules/@whiskeysockets/baileys/package.json"
    socket = bridge / "node_modules/@whiskeysockets/baileys/lib/Socket/socket.js"
    utility = bridge / "node_modules/@whiskeysockets/baileys/lib/Utils/companion-reg-client-utils.js"
    messages = bridge / "node_modules/@whiskeysockets/baileys/lib/Socket/messages-recv.js"

    for path in (package, socket, utility, messages):
        if not path.is_file():
            raise PatchError(f"Missing Baileys patch target: {path}")

    version = json.loads(package.read_text())["version"]
    if version != BAILEYS_VERSION:
        raise PatchError(
            f"Baileys {version} is not the reviewed target {BAILEYS_VERSION}; "
            "reassess the compatibility patch instead of applying it blindly"
        )

    original = {
        socket: socket.read_text(),
        utility: utility.read_text(),
        messages: messages.read_text(),
    }

    socket_text = original[socket]
    socket_text = replace_once(
        socket_text,
        "getNextPreKeysNode, makeEventBuffer, makeNoiseHandler, promiseTimeout",
        "getNextPreKeysNode, handleCompanionRegRefresh, makeEventBuffer, "
        "makeNoiseHandler, makePairingQRRenderer, promiseTimeout",
        "socket utility import",
    )
    socket_text = replace_once(
        socket_text,
        "    // QR gen\n",
        "    // Re-render the QR currently on screen while a pairing flow is active.\n"
        "    let refreshPairingQR;\n"
        "    // QR gen\n",
        "pairing renderer declaration",
    )
    socket_text = replace_once(
        socket_text,
        """        const advB64 = creds.advSecretKey;
        let qrMs = qrTimeout || 60000; // time to let a QR live
        const genPairQR = () => {
            if (!ws.isOpen) {
                return;
            }
            const refNode = refNodes.shift();
            if (!refNode) {
                void end(new Boom('QR refs attempts ended', { statusCode: DisconnectReason.timedOut }));
                return;
            }
            const ref = refNode.content.toString('utf-8');
            const qr = buildPairingQRData(ref, noiseKeyB64, identityKeyB64, advB64, browser);
            ev.emit('connection.update', { qr });
            qrTimer = setTimeout(genPairQR, qrMs);
            qrMs = qrTimeout || 20000; // shorter subsequent qrs
        };
        genPairQR();
    });
""",
        """        const renderer = makePairingQRRenderer(refNodes.map(refNode => refNode.content.toString('utf-8')), ref => ev.emit('connection.update', {
            qr: buildPairingQRData(ref, noiseKeyB64, identityKeyB64, creds.advSecretKey, browser)
        }));
        refreshPairingQR = () => void renderer.refresh();
        let qrMs = qrTimeout || 60000; // time to let a QR live
        const genPairQR = () => {
            if (!ws.isOpen) {
                return;
            }
            if (!renderer.next()) {
                void end(new Boom('QR refs attempts ended', { statusCode: DisconnectReason.timedOut }));
                return;
            }
            qrTimer = setTimeout(genPairQR, qrMs);
            qrMs = qrTimeout || 20000; // shorter subsequent qrs
        };
        genPairQR();
    });
    ws.on('CB:notification,type:companion_reg_refresh', (node) => {
        handleCompanionRegRefresh(node, {
            creds,
            emitCredsUpdate: update => ev.emit('creds.update', update),
            refreshQR: () => refreshPairingQR?.(),
            logger
        });
    });
""",
        "QR generation and refresh handler",
    )

    utility_text = original[utility]
    utility_text = replace_once(
        utility_text,
        "export var CompanionWebClientType;",
        "import { randomBytes } from 'crypto';\n"
        "import { getBinaryNodeChild } from '../WABinary/index.js';\n"
        "export var CompanionWebClientType;",
        "companion refresh imports",
    )
    utility_text = replace_once(
        utility_text,
        "//# sourceMappingURL=companion-reg-client-utils.js.map",
        """export const makePairingQRRenderer = (refs, render) => {
    let index = 0;
    let current;
    return {
        next() {
            const ref = refs[index];
            if (ref === undefined) {
                return false;
            }
            index += 1;
            current = ref;
            render(ref);
            return true;
        },
        refresh() {
            if (current === undefined) {
                return false;
            }
            render(current);
            return true;
        }
    };
};
const COMPANION_REG_REFRESH_CHILDREN = ['companion_reg_refresh', 'pair-device-rotate-qr'];
export const handleCompanionRegRefresh = (node, { creds, emitCredsUpdate, refreshQR, logger }) => {
    if (!COMPANION_REG_REFRESH_CHILDREN.some(tag => getBinaryNodeChild(node, tag))) {
        logger.warn({ node }, 'companion_reg_refresh carries neither expected child; ignoring');
        return 'ignored_malformed';
    }
    if (creds.me) {
        logger.debug({ id: node.attrs.id }, 'companion_reg_refresh on a registered session; keeping the adv secret');
        return 'ignored_registered';
    }
    creds.advSecretKey = randomBytes(32).toString('base64');
    emitCredsUpdate({ advSecretKey: creds.advSecretKey });
    logger.info({ id: node.attrs.id }, 'rotated retired adv secret; re-rendering pairing QR');
    refreshQR();
    return 'rotated';
};
//# sourceMappingURL=companion-reg-client-utils.js.map""",
        "companion refresh implementation",
    )

    messages_text = replace_once(
        original[messages],
        "buildAckStanza(node, errorCode, authState.creds.me.id)",
        "buildAckStanza(node, errorCode, authState.creds.me?.id)",
        "pre-login notification acknowledgement",
    )

    updated = {socket: socket_text, utility: utility_text, messages: messages_text}
    changed = False
    for path, text in updated.items():
        if text != original[path]:
            path.write_text(text)
            changed = True

    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify that the reviewed compatibility patch is already present",
    )
    args = parser.parse_args()
    bridge = args.bridge.resolve()
    if args.check:
        if bridge_is_patched(bridge):
            print(
                "Baileys compatibility patch verified "
                f"(PR #2765 {PR_2765_COMMIT}, PR #2749 {PR_2749_COMMIT})"
            )
            return 0
        parser.exit(1, f"Baileys compatibility patch is missing or invalid: {bridge}\n")
    try:
        changed = patch_bridge(bridge)
    except (OSError, KeyError, json.JSONDecodeError, PatchError) as error:
        parser.exit(1, f"Baileys pairing patch failed: {error}\n")
    state = "applied" if changed else "already applied"
    print(
        f"Baileys pairing compatibility patch {state} "
        f"(PR #2765 {PR_2765_COMMIT}, PR #2749 {PR_2749_COMMIT})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
