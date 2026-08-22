"""
handlers/loadout.py — GET /ares/loadout/api/user/{xuid}/pirate/{pirateId}/loadout.

**Why this exists (root cause of "the pirate has no weapons/tools/emotes"):**
every `/ares/*` response body in fixtures/data/ that matters for equipment
(loadout, pirate, pirateslot*, commercev2/entitlement, ship, shiploadout,
emblemv3, ...) is tagged `"X-Encoding": "sot"` — Rare's own app-layer
AES-GCM encryption on top of TLS, keyed by a value read from Unreal's
`GConfig` (`[OnlineSecurity] DefaultKey`), confirmed via Ghidra
(`FUN_7ff64d546040`/`FUN_7ff64d548010`, BCRYPT_AES + ChainingModeGCM). That
key was never recovered (see project memory:
sot-lighthouse-vs-mpsd-diagnosis.md), and — separately fatal on its own —
the captured fixtures themselves are from a DIFFERENT client build
(2.150.9409.0) than the one being emulated (2.95.1936.0, see
handlers/login.py's OLD_BUILD_VERSION), which almost certainly uses a
DIFFERENT build-specific key even if we had it. So `app.py`'s fixture
replay for these paths sends back genuine-looking bytes that this client
can never decrypt — functionally identical to sending nothing, which is
exactly the symptom (empty hands, empty tool belt, empty emote wheel).

**Why a handler instead of a fixture:** we can't forge valid AES-GCM
ciphertext without the key, but we don't need to — `handlers/login.py`
already proved this old client accepts a genuine, UNENCRYPTED
`application/json` response (no `X-Encoding` header at all) for at least
one `/ares/*` endpoint and behaves correctly. This handler takes the same
approach for `loadout`: skip the fixture/encryption path entirely and
answer with plain JSON built by us.

**Confidence level — this is a guess, like handlers/customgame.py's
permission fields:** the real Ares loadout JSON schema for this build has
never been seen in plaintext (every capture is ciphertext), so exact field
names are unknown. Following this project's established practice (extra
unknown JSON keys are harmless, so include every plausible name rather
than commit to one guess), each item below carries several synonymous
id/name/slot keys, and the top-level object exposes the same item list
under several plausible container keys. `PascalCase` was chosen because
it's the one confirmed-real convention we have from a genuinely
plaintext(!) fixture: `GET .../notifications/withoffset` →
`{"Message":""}`.

**Item choice**: the three weapons/tools every new Sea of Thieves pirate
has always started with regardless of account age or purchases (not DLC,
not entitlement-gated) — Cutlass (melee), Flintlock Pistol (firearm),
Blunderbuss (second firearm), Shovel/Bucket/Lantern (tools) — plus a small
default emote set. If live testing (Frida log of what the client actually
reads, or simply observing what appears in-game) shows this doesn't stick,
the next step is capturing what fields the client's own JSON parser
touches rather than guessing further blind — see this file's sibling
handlers for the same discipline (contestmatchmaking.py, customgame.py).
"""
from __future__ import annotations

import logging

from aiohttp import web

from . import route

log = logging.getLogger("emulator.loadout")


def _item(item_id: str, name: str, slot: str, category: str) -> dict:
    """One equipped item, expressed with several plausible key-name
    synonyms per field — see module docstring."""
    return {
        "Id": item_id,
        "ItemId": item_id,
        "ArchetypeName": item_id,
        "Name": name,
        "DisplayName": name,
        "Slot": slot,
        "SlotType": slot,
        "EquipSlot": slot,
        "Category": category,
        "Type": category,
        "Quantity": 1,
        "Count": 1,
        "IsEquipped": True,
        "Equipped": True,
    }


_DEFAULT_EQUIPPED = [
    _item("Weapon_Cutlass_Standard", "Cutlass", "MeleeWeapon", "Weapon"),
    _item("Weapon_Pistol_Standard", "Flintlock Pistol", "Firearm", "Weapon"),
    _item("Weapon_Blunderbuss_Standard", "Blunderbuss", "Firearm2", "Weapon"),
    _item("Tool_Shovel_Standard", "Shovel", "Tool", "Tool"),
    _item("Tool_Bucket_Standard", "Bucket", "Tool", "Tool"),
    _item("Tool_Lantern_Standard", "Lantern", "Tool", "Tool"),
]

_DEFAULT_EMOTES = [
    _item("Emote_Wave", "Wave", "Emote", "Emote"),
    _item("Emote_RudeGesture", "Rude Gesture", "Emote", "Emote"),
    _item("Emote_Laugh", "Laugh", "Emote", "Emote"),
    _item("Emote_Dance", "Dance", "Emote", "Emote"),
    _item("Emote_Cheer", "Cheer", "Emote", "Emote"),
    _item("Emote_Point", "Point", "Emote", "Emote"),
    _item("Emote_Salute", "Salute", "Emote", "Emote"),
    _item("Emote_Bow", "Bow", "Emote", "Emote"),
]

_ALL_ITEMS = _DEFAULT_EQUIPPED + _DEFAULT_EMOTES


@route("GET", "/ares/loadout/api/user/2535422034996422/pirate/5ec725b9-6c28-43ff-82ad-cad08c811c22/loadout")
async def get_loadout(request: web.Request) -> web.Response:
    body = {
        # every plausible container key for "the list of items", same list
        # repeated under each — see module docstring on why
        "Items": _ALL_ITEMS,
        "EquippedItems": _ALL_ITEMS,
        "LoadoutItems": _ALL_ITEMS,
        "Loadout": {"Items": _ALL_ITEMS},
        "Weapons": _DEFAULT_EQUIPPED,
        "Tools": [i for i in _DEFAULT_EQUIPPED if i["Category"] == "Tool"],
        "Emotes": _DEFAULT_EMOTES,
        "EmoteWheel": _DEFAULT_EMOTES,
        "Result": "Success",
    }
    log.info("[loadout] GET loadout -> %d items (plaintext override, see handlers/loadout.py docstring)", len(_ALL_ITEMS))
    return web.json_response(body)
