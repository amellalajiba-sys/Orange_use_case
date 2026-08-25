"""Shared guardrails for terms proposed as taxonomy extensions."""

# Sieg 24/8 -- shared guardrail used by both the LLM extraction path and the
# human-review path, so a bare generic label cannot slip through one of them.
# These labels are too broad to distinguish an Opportunity Space. Keep this
# deliberately narrow: compound, specific labels such as "Generative AI" are
# valid technologies and must not be filtered out.
GENERIC_TECHNOLOGY_TERMS = frozenset({"ai", "artificial intelligence"})


def is_generic_taxonomy_term(term, category):
    """Return whether a proposed taxonomy term is too generic to approve."""
    if category != "technology" or not isinstance(term, str):
        return False
    return term.strip().casefold() in GENERIC_TECHNOLOGY_TERMS
