"""Interaction-analysis facade.

Vina uses the transparent legacy PLIP-compatible geometry implementation;
Boltz structures use native PLIP. Keeping these names separate prevents a
scientifically misleading method label.
"""

from drug_discovery_agent.plip.runner import parse_plip_xml, run_plip_jobs
from drug_discovery_agent.vina.interactions import analyze_interactions, binding_site_residues

__all__ = ["analyze_interactions", "binding_site_residues", "parse_plip_xml", "run_plip_jobs"]

