from __future__ import annotations

from pathlib import Path

from drug_discovery_agent.plip.runner import parse_plip_xml


def test_native_plip_xml_is_parsed_structurally(tmp_path: Path) -> None:
    report = tmp_path / "report.xml"
    report.write_text(
        "<report><bindingsite><interactions><hydrogen_bonds>"
        "<hydrogen_bond><resnr>84</resnr><restype>VAL</restype><dist_d-a>3.2</dist_d-a>"
        "</hydrogen_bond></hydrogen_bonds></interactions></bindingsite></report>",
        encoding="utf-8",
    )
    rows = parse_plip_xml(report)
    assert rows == [{"interaction_type": "hydrogen_bond", "resnr": "84",
                     "restype": "VAL", "dist_d-a": "3.2"}]

