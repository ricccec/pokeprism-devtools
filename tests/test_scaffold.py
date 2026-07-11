#!/usr/bin/env python3
"""Tests for the content scaffolds: NPCs, trainers, item balls, hidden items,
and the trainer-party and wild-data editors underneath them.

The unit tests are hermetic. The ones that matter most aren't: they parse every
real trainer group and every real wild table, because these files are read
*positionally* by the engine — a party is found by counting, and a wild block by
its fixed stride — so a parser that miscounts by one is a parser that silently
rewrites somebody else's trainer.

    python tests/test_scaffold.py
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pokeprism_devtools.shared import (  # noqa: E402
    eventheader as eh, landmarks, trainerparty as tp, wilddata as wd,
)
from pokeprism_devtools.shared.edits import apply_edits  # noqa: E402
from pokeprism_devtools.wiring import scaffold as sc  # noqa: E402

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


def raises(label: str, fn, *, wanted: str = "") -> None:
    """Check that `fn` refuses, and that it says why."""
    try:
        fn()
        check(label, False, "no error raised")
    except (sc.ScaffoldError, tp.TrainerPartyError, wd.WildDataError) as e:
        check(label, wanted in str(e), str(e) if wanted not in str(e) else "")


# --------------------------------------------------------------------------- #
# fixture                                                                     #
# --------------------------------------------------------------------------- #

def _fixture(tmp: Path) -> Path:
    root = tmp / "repo"
    for d in ("constants", "maps", "trainers/groups", "data/wild"):
        (root / d).mkdir(parents=True)

    (root / "constants.asm").write_text(
        '\tconst_def\n\tconst EVENT_0\n\tINCLUDE "constants/event_flags.asm"\n'
    )
    (root / "constants/event_flags.asm").write_text(
        "\tconst EVENT_1\n\tconst skip\n\tconst skip\n\tconst skip\n\tconst skip\n"
    )
    (root / "constants/pokemon_constants.asm").write_text(
        "\tconst_def\n\tconst PIDGEY\n\tconst SENTRET\n\tconst ZUBAT\n"
    )
    (root / "constants/item_constants.asm").write_text(
        "\tconst_def\n\tconst ULTRA_BALL\n\tconst RARE_CANDY\n\tconst ORAN_BERRY\n"
    )
    (root / "constants/move_constants.asm").write_text(
        "\tconst_def\n\tconst TACKLE\n\tconst GROWL\n\tconst NO_MOVE\n"
    )
    (root / "constants/landmark_constants.asm").write_text(
        "\tconst_def\n\tregion_def JOHTO\n\tconst LM_A\n"
        "\tregion_def NALJO\n\tconst LM_B\n"
    )
    (root / "constants/map_constants.asm").write_text(
        "\tconst_def\n\tconst TOWN\n\tconst ROUTE\n"
    )

    # sprites: ids, movement data, palettes — the enums an Object is checked against
    (root / "constants/sprite_constants.asm").write_text(
        "\tconst_def\n"
        "\tconst SPRITE_SAGE\n\tconst SPRITE_YOUNGSTER\n\tconst SPRITE_POKE_BALL\n"
        "SPRITE_POKEMON EQU const_value\nSPRITE_VARS EQU const_value + 10\n"
        "\n\tconst_def\n\tconst SPRITE_ANIM_FRAMESET_DECOY\n"
        "\n\tconst_def\n"
        "\tconst SPRITEMOVEDATA_STANDING_DOWN\n\tconst SPRITEMOVEDATA_ITEM_TREE\n"
        "\tconst SPRITEMOVEDATA_WALK_UP_DOWN\n"
        "\n\tconst_def\n\tconst PAL_OW_RED\n\tconst PAL_OW_BLUE\n"
    )
    (root / "maps/map_headers.asm").write_text(
        "\tmap_header TownA, TS, TOWN, LM_A, MU, 0, PAL, F0\n"
        "\tmap_header RouteB, TS, ROUTE, LM_B, MU, 0, PAL, F0\n"
    )
    (root / "maps/second_map_headers.asm").write_text(
        "\tmap_header_2 TownA, TOWN_A, $f, 0\n"
        "\tmap_header_2 RouteB, ROUTE_B, $f, 0\n"
    )
    (root / "maps/TownA.asm").write_text(
        "TownAGreeter:\n\tctxt \"Hello.\"\n\tdone\n\n"
        "TownA_MapEventHeader:: db 0, 0\n\n"
        ".Warps\n\tdb 0\n\n.CoordEvents\n\tdb 0\n\n"
        ".BGEvents\n\tdb 0\n\n.ObjectEvents\n\tdb 0\n"
    )

    # one trainer class, with the pointer table that binds it
    (root / "constants/trainer_constants.asm").write_text(
        "\tconst_def\n\ttrainerclass TRAINER_NONE\n"
        "\ttrainerclass YOUNGSTER\n\ttrainerclass SAGE\n\ttrainerclass GHOST\n"
    )
    (root / "trainers/trainer_pointers.asm").write_text(
        "TrainerGroups:\n\tdw YoungsterGroup\n\tdw NULL ;Sage\n"
    )
    (root / "trainers/groups/youngster.asm").write_text(
        'YoungsterGroup:\n\t; 1\n\tdb "Jordan@"\n\n\tdb TRAINERTYPE_NORMAL\n\n'
        "\tdb 4, PIDGEY\n\tdb -1\n\n"
        '\t; 2\n\tdb "Wilson@"\n\n\tdb TRAINERTYPE_ITEM\n\n'
        "\tdb 5, ZUBAT, ORAN_BERRY\n\tdb -1\n"
    )

    (root / "data/wild/naljo_grass.asm").write_text(
        "\twildmap ROUTE_B\n\tdb 5 percent, 5 percent, 5 percent\n"
        + "\t; morn\n" + "".join(f"\tdb {i}, PIDGEY\n" for i in range(1, 8))
        + "\t; day\n" + "".join(f"\tdb {i}, ZUBAT\n" for i in range(1, 8))
        + "\t; nite\n" + "".join(f"\tdb {i}, ZUBAT\n" for i in range(1, 8))
        + "\n\tendwildmap\n"
    )
    return root


# --------------------------------------------------------------------------- #
# trainer parties — read positionally, so counting is the whole game          #
# --------------------------------------------------------------------------- #

def test_parties(root: Path) -> None:
    print("\nparties are found by counting, so appending is the only safe edit")
    group = tp.group_for(root, "YOUNGSTER")
    check("resolved through TrainerGroups, not by name", group.label == "YoungsterGroup")
    check("two parties", group.count == 2)
    check("party 1 is 1-based", group.party(1).name == "Jordan")
    check("a TRAINERTYPE_ITEM mon keeps its held item",
          group.party(2).mons[0].item == "ORAN_BERRY")

    added = group.add_party("Testy", [tp.Mon(9, "SENTRET")], tp.NORMAL)
    check("a new party lands at the end, with the next index", added.index == 3)
    check("the existing parties keep their indices",
          [p.index for p in group.parties] == [1, 2, 3])
    check("the `; n` comment is regenerated from position",
          "\t; 3\n" in group.to_text())
    check("Jordan is untouched", group.party(1).name == "Jordan")

    raises("an empty party is refused",
           lambda: group.add_party("Empty", [], tp.NORMAL), wanted="no Pokemon")
    raises("a MOVES party must carry exactly four moves",
           lambda: group.add_party("M", [tp.Mon(5, "PIDGEY", moves=("TACKLE",))], tp.MOVES),
           wanted="exactly 4 moves")
    raises("an ITEM party must carry a held item on every mon",
           lambda: group.add_party("I", [tp.Mon(5, "PIDGEY")], tp.ITEM),
           wanted="held item")


def test_unbacked_classes(root: Path) -> None:
    print("\na class with no parties behind it cannot be battled")
    unbacked = tp.unbacked_classes(root)
    check("a `dw NULL` slot is unbacked", "SAGE" in unbacked)
    check("a class past the end of the table is unbacked", "GHOST" in unbacked)
    check("and it says the table ran out", "runs out" in unbacked.get("GHOST", ""))
    check("a real class is not", "YOUNGSTER" not in unbacked)


# --------------------------------------------------------------------------- #
# wild data — fixed stride, and the region comes from the landmark            #
# --------------------------------------------------------------------------- #

def test_wild(root: Path) -> None:
    print("\nwild blocks are fixed-size, and the region is not the caller's choice")
    check("the region comes from the map's landmark",
          landmarks.region_of_map(root, "ROUTE_B") == "naljo")

    table = wd.table_for(root, "ROUTE_B", wd.GRASS)
    check("which picks the file", table.path.name == "naljo_grass.asm")
    block = table.find("ROUTE_B")
    check("the existing block parses", block is not None and block.rates == [5, 5, 5])
    check("7 slots per time of day", all(len(block.mons[t]) == 7 for t in table.times))

    mons = {t: [wd.Encounter(3, "ZUBAT")] * 7 for t in table.times}
    table.set_block("ROUTE_B", [10, 10, 10], mons)
    check("an existing block is replaced, not duplicated", len(table.blocks) == 1)
    check("with the new rate", table.find("ROUTE_B").rates == [10, 10, 10])

    table.set_block("TOWN_A", [4, 4, 4], mons)
    check("a new block appends before endwildmap", len(table.blocks) == 2)
    check("and stays inside the table",
          table.to_text().index("wildmap TOWN_A") < table.to_text().index("endwildmap"))

    raises("a short block is refused — it would shift every map below it",
           lambda: table.set_block("TOWN_A", [4, 4, 4],
                                   {t: [wd.Encounter(3, "ZUBAT")] for t in table.times}),
           wanted="fixed-size")

    print("\n  a bare `db 3` rate is 3/255, not 3%")
    raw = wd.WildBlock("X", [3, 3, 3], raw_rates=True)
    pct = wd.WildBlock("X", [3, 3, 3], raw_rates=False)
    check("bare bytes mean themselves", raw.rate_bytes == [3, 3, 3])
    check("`3 percent` scales by 255/100", pct.rate_bytes == [7, 7, 7])


# --------------------------------------------------------------------------- #
# the scaffolds                                                               #
# --------------------------------------------------------------------------- #

def _reset(root: Path, saved: dict[str, str]) -> None:
    for rel, text in saved.items():
        (root / rel).write_text(text)


def _snapshot(root: Path) -> dict[str, str]:
    rels = ["maps/TownA.asm", "constants/event_flags.asm", "trainers/groups/youngster.asm"]
    return {rel: (root / rel).read_text() for rel in rels}


def test_npc(root: Path) -> None:
    print("\nan NPC: a text block above the header, a person_event below it")
    saved = _snapshot(root)
    s = sc.add_npc(root, "TOWN_A",
                   sc.Object("SPRITE_YOUNGSTER", 5, 6, palette="PAL_OW_BLUE"),
                   pages=[["Hi there,", "traveller."], ["Mind the", "grass."]])
    apply_edits(root, s.edits, dry_run=False)
    text = (root / "maps/TownA.asm").read_text()

    check("the label avoids the one already in the file", s.label == "TownANPC")
    check("dialogue opens with ctxt", '\tctxt "Hi there,"' in text)
    check("the second row is `line`", '\tline "traveller."' in text)
    check("a new textbox is `para`", '\tpara "Mind the"' in text)
    check("and it ends with done", text.count("\tdone") == 2)
    check("the text block sits above the event header",
          text.index("TownANPC:") < text.index("TownA_MapEventHeader::"))
    check("the person_event points at it",
          "PERSONTYPE_TEXT, 0, TownANPC, -1" in text)
    check("the object count went 0 -> 1",
          eh.parse_map(root / "maps/TownA.asm").lists[eh.ListKind.OBJECT_EVENTS].declared_count == 1)
    check("no flag was allocated for an always-there NPC", s.flag is None)
    _reset(root, saved)


def test_trainer(root: Path) -> None:
    print("\na trainer: flag + party + macro + three texts, or nothing at all")
    saved = _snapshot(root)
    s = sc.add_trainer(root, "TOWN_A",
                       sc.Object("SPRITE_YOUNGSTER", 7, 8, behind_bg=True),
                       cls="YOUNGSTER",
                       new_party=("Testy", [tp.Mon(9, "SENTRET")], tp.NORMAL),
                       seen=[["You!"]], defeated=[["Ugh."]], after=[["Nice."]], sight=2)
    check("it touches three files", len(s.changes) == 3)
    apply_edits(root, s.edits, dry_run=False)

    text = (root / "maps/TownA.asm").read_text()
    check("the party was appended, not inserted", s.party == 3)
    check("the flag reused a `const skip` slot",
          "\tconst EVENT_TOWN_A_TRAINER_1\n" in (root / "constants/event_flags.asm").read_text())
    check("the macro cites flag, class and party",
          f"\ttrainer {s.flag}, YOUNGSTER, 3, .before_battle_text, .defeated_text" in text)
    check("the talk-again text falls through under the macro",
          text.index('ctxt "Nice."') < text.index("\n.before_battle_text\n"))
    check("both other texts are local labels",
          "\n.before_battle_text\n" in text and "\n.defeated_text\n" in text)
    check("behind_bg becomes the OAM-priority bit", "8 + PAL_OW_RED" in text)
    check("the person_event carries the sight radius",
          f"PERSONTYPE_GENERICTRAINER, 2, {s.label}, -1" in text)

    raises("a class whose TrainerGroups slot is NULL is refused",
           lambda: sc.add_trainer(root, "TOWN_A", sc.Object("SPRITE_SAGE", 1, 1),
                                  cls="SAGE", party=1,
                                  seen=[["a"]], defeated=[["b"]], after=[["c"]]),
           wanted="NULL")
    raises("a party index past the end is refused",
           lambda: sc.add_trainer(root, "TOWN_A", sc.Object("SPRITE_YOUNGSTER", 1, 1),
                                  cls="YOUNGSTER", party=99,
                                  seen=[["a"]], defeated=[["b"]], after=[["c"]]),
           wanted="doesn't exist")
    _reset(root, saved)


def test_items(root: Path) -> None:
    print("\nitem balls and hidden items")
    saved = _snapshot(root)
    s = sc.add_itemball(root, "TOWN_A", 3, 4, "ULTRA_BALL")
    apply_edits(root, s.edits, dry_run=False)
    text = (root / "maps/TownA.asm").read_text()
    check("the flag is named for map and item",
          s.flag == "EVENT_TOWN_A_ITEM_ULTRA_BALL")
    check("the item const sits where a script pointer would",
          f"PERSONTYPE_ITEMBALL, 1, ULTRA_BALL, {s.flag}" in text)

    h = sc.add_hidden_item(root, "TOWN_A", 9, 10, "RARE_CANDY")
    apply_edits(root, h.edits, dry_run=False)
    text = (root / "maps/TownA.asm").read_text()
    check("a hidden item gets a flag+item record",
          f"{h.label}:\n\tdw {h.flag}\n\tdb RARE_CANDY" in text)
    check("and a SIGNPOST_ITEM pointing at it",
          f"signpost 9, 10, SIGNPOST_ITEM, {h.label}" in text)
    check("which lands in BGEvents, count 0 -> 1",
          eh.parse_map(root / "maps/TownA.asm").lists[eh.ListKind.BG_EVENTS].declared_count == 1)
    _reset(root, saved)


def test_rejects_unknown_consts(root: Path) -> None:
    print("\nan unknown constant is caught here, not by rgblink five minutes later")
    npc = lambda **kw: sc.add_npc(root, "TOWN_A", sc.Object(**kw), pages=[["hi"]])
    raises("a sprite that doesn't exist",
           lambda: npc(sprite="SPRITE_YOUNGSTR", y=1, x=1), wanted="Did you mean SPRITE_YOUNGSTER")
    raises("a movement that doesn't exist",
           lambda: npc(sprite="SPRITE_SAGE", y=1, x=1, movement="SPRITEMOVEDATA_NOPE"),
           wanted="not a movement")
    raises("a palette that doesn't exist",
           lambda: npc(sprite="SPRITE_SAGE", y=1, x=1, palette="PAL_OW_PINK"),
           wanted="not a palette")
    raises("an item that doesn't exist",
           lambda: sc.add_itemball(root, "TOWN_A", 1, 1, "ULTRABALL"),
           wanted="Did you mean ULTRA_BALL")
    raises("a species this fork doesn't have",
           lambda: sc.add_trainer(root, "TOWN_A", sc.Object("SPRITE_SAGE", 1, 1),
                                  cls="YOUNGSTER",
                                  new_party=("T", [tp.Mon(5, "RATTATA")], tp.NORMAL),
                                  seen=[["a"]], defeated=[["b"]], after=[["c"]]),
           wanted="not a species")

    print("\n  and nothing is written when it is")
    before = _snapshot(root)
    try:
        sc.add_itemball(root, "TOWN_A", 1, 1, "NOPE_BALL")
    except sc.ScaffoldError:
        pass
    check("the map is untouched", _snapshot(root) == before)


# --------------------------------------------------------------------------- #
# the real repo                                                               #
# --------------------------------------------------------------------------- #

def _real_repo() -> Path | None:
    for cand in (Path.home() / "code/ricccec/pokeprism",
                 Path(__file__).resolve().parent.parent.parent / "pokeprism"):
        if (cand / "maps/map_headers.asm").exists():
            return cand
    return None


def test_real_parsers(tmp: Path) -> None:
    root = _real_repo()
    if root is None:
        print("\n(no pokeprism checkout found — skipping the real-repo checks)")
        return

    print("\nevery real trainer group, read positionally")
    groups = tp.load(root)
    parties = sum(g.count for g in groups.values())
    check(f"{len(groups)} groups, {parties} parties", parties > 300)
    check("every group file round-trips byte-for-byte",
          all(g.to_text() == g.path.read_text() for g in groups.values()))

    misnumbered = [
        f"{g.label}#{p.index}"
        for g in groups.values() for p in g.parties
        if (m := re.match(r"^;\s*(\d+)$", g.lines[p.start - 1].strip())) and int(m.group(1)) != p.index
    ]
    check("every `; n` comment agrees with the party's real position",
          not misnumbered, ", ".join(misnumbered[:3]))

    cited = 0
    for f in sorted((root / "maps").glob("*.asm")):
        for line in f.read_text().split("\n"):
            m = re.match(r"^\s*trainer\s+\w+\s*,\s*(\w+)\s*,\s*(\w+)\s*,", line)
            if not m:
                continue
            cited += 1
            group = groups.get(tp.class_groups(root).get(m.group(1)) or "")
            if group is None or not m.group(2).isdigit():
                continue
            if not 1 <= int(m.group(2)) <= group.count:
                check(f"{f.name}: {m.group(1)} #{m.group(2)}", False, "out of range")
    check(f"all {cited} trainer citations in the repo resolve to a real party", cited > 250)

    print("\nevery real wild table, read at its fixed stride")
    blocks = 0
    for path in sorted((root / "data/wild").glob("*.asm")):
        if path.stem == "fish":
            continue
        region, _, kind = path.stem.rpartition("_")
        table = wd.load(root, region, kind)
        if table.to_text() != path.read_text():
            check(f"{path.name} round-trips", False)
        blocks += len(table.blocks)
    check(f"{blocks} wildmap blocks parse and round-trip byte-for-byte", blocks > 150)


def test_real_scaffold(tmp: Path) -> None:
    """Scaffold real content into a real map, and check the linter finds nothing
    new — the tool built to find broken maps is the one that should judge this."""
    root = _real_repo()
    if root is None:
        return

    from collections import Counter
    from pokeprism_devtools.maplint import (
        context, rules_content, rules_geometry, rules_objects, rules_sprites,
    )

    def lint(at: Path) -> Counter:
        ctx = context.LintContext(at)
        found = []
        for mod in (rules_geometry, rules_objects, rules_sprites, rules_content):
            for rule in mod.ALL:
                found += rule(ctx)
        return Counter((d.code, d.path) for d in found)

    print("\nscaffolding into a real map, judged by the linter")
    scratch = tmp / "pokeprism"
    shutil.copytree(root, scratch, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "*.o", "*.gbc", "*.sym", "*.map"))
    before = lint(scratch)

    MAP = "CASTRO_FOREST"
    for s in (
        sc.add_npc(scratch, MAP, sc.Object("SPRITE_YOUNGSTER", 12, 20, palette="PAL_OW_BLUE"),
                   pages=[["Hi! I'm new", "around here."]]),
        sc.add_trainer(scratch, MAP,
                       sc.Object("SPRITE_SAGE", 14, 22, palette="PAL_OW_BLUE", behind_bg=True),
                       cls="SAGE", party=6, sight=3,
                       seen=[["You there!"]], defeated=[["I yield."]], after=[["Well fought."]]),
        sc.add_trainer(scratch, MAP, sc.Object("SPRITE_YOUNGSTER", 16, 8), cls="YOUNGSTER",
                       new_party=("Testy", [tp.Mon(12, "SENTRET")], tp.NORMAL),
                       seen=[["Let's go!"]], defeated=[["Aw, man."]], after=[["Good game."]]),
        sc.add_itemball(scratch, MAP, 20, 30, "ULTRA_BALL"),
        sc.add_hidden_item(scratch, MAP, 5, 6, "RARE_CANDY"),
    ):
        apply_edits(scratch, s.edits, dry_run=False)

    after = lint(scratch)
    new, gone = after - before, before - after
    check("the linter finds nothing new anywhere in the repo", not new, str(dict(new)))
    check("and nothing that was there before has been disturbed", not gone, str(dict(gone)))

    path = scratch / "maps/CastroForest.asm"
    check("the map still round-trips byte-for-byte",
          eh.parse_map(path).to_text() == path.read_text())
    check("the new trainer's party really is in the group file",
          tp.group_for(scratch, "YOUNGSTER").find("Testy") is not None)


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        root = _fixture(tmp)
        test_parties(root)
        test_unbacked_classes(root)
        test_wild(root)
        test_npc(root)
        test_trainer(root)
        test_items(root)
        test_rejects_unknown_consts(root)
        test_real_parsers(tmp)
        test_real_scaffold(tmp)

    print()
    if _failures:
        print(f"{_failures} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
