#!/usr/bin/env python3
"""
skos_hierarchy.py — Print the concept hierarchy of a SKOS vocabulary file.

Usage:
    python skos_hierarchy.py <vocab_file> [--lang LANG]

Arguments:
    vocab_file   Path to the SKOS file (Turtle, RDF/XML, JSON-LD, N-Triples…)
    --lang       Preferred language tag for labels (default: en)

Example:
    python skos_hierarchy.py my_thesaurus.ttl
    python skos_hierarchy.py unesco.rdf --lang fr
"""

import sys
import argparse
from rdflib import Graph, Namespace, URIRef, RDFS
from rdflib.namespace import SKOS, RDF

# ── ANSI colours (disabled automatically on non-TTY) ─────────────────────────
USE_COLOR = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

BOLD   = lambda t: _c("1",      t)
DIM    = lambda t: _c("2",      t)
CYAN   = lambda t: _c("1;36",   t)
YELLOW = lambda t: _c("1;33",   t)
GREEN  = lambda t: _c("32",     t)
GREY   = lambda t: _c("90",     t)

# ── Label resolution ──────────────────────────────────────────────────────────

def get_label(graph: Graph, uri: URIRef, lang: str) -> str:
    """Return the best human-readable label for *uri*."""
    # Priority: prefLabel (target lang) → prefLabel (any) → label → local name
    candidates = []
    for pred in (SKOS.prefLabel, SKOS.altLabel, RDFS.label):
        for obj in graph.objects(uri, pred):
            obj_str = str(obj)
            obj_lang = getattr(obj, "language", None)
            if obj_lang == lang:
                return obj_str                      # exact language match → done
            candidates.append((obj_lang, obj_str))

    if candidates:
        # prefer labels without a language tag, then any
        for obj_lang, text in candidates:
            if obj_lang is None:
                return text
        return candidates[0][1]

    # Fall back to the local name part of the URI
    fragment = uri.split("#")[-1] if "#" in uri else uri.split("/")[-1]
    return fragment or str(uri)


# ── Tree builder ──────────────────────────────────────────────────────────────

def build_children(graph: Graph) -> dict:
    """Return {parent_uri: [child_uri, …]} from skos:narrower / skos:broader."""
    children: dict = {}

    # Collect all concepts
    all_concepts = set(graph.subjects(RDF.type, SKOS.Concept))
    for uri in all_concepts:
        children.setdefault(uri, [])

    # skos:narrower  (parent → child)
    for parent, _, child in graph.triples((None, SKOS.narrower, None)):
        if isinstance(child, URIRef):
            children.setdefault(parent, [])
            children[parent].append(child)

    # skos:broader   (child → parent)  — inverse direction
    for child, _, parent in graph.triples((None, SKOS.broader, None)):
        if isinstance(parent, URIRef):
            children.setdefault(parent, [])
            if child not in children[parent]:
                children[parent].append(child)

    return children


def find_roots(graph: Graph, children: dict) -> list:
    """
    Top concepts are those explicitly marked as skos:hasTopConcept / skos:topConceptOf,
    or concepts with no broader parent at all.
    """
    explicit_tops = set()
    for _, _, tc in graph.triples((None, SKOS.hasTopConcept, None)):
        explicit_tops.add(tc)
    for tc, _, _ in graph.triples((None, SKOS.topConceptOf, None)):
        explicit_tops.add(tc)

    if explicit_tops:
        return sorted(explicit_tops, key=str)

    # Fallback: concepts that appear as no one's child
    has_broader = {
        child
        for child, _, _ in graph.triples((None, SKOS.broader, None))
    }
    all_children = {c for kids in children.values() for c in kids}
    all_broader  = has_broader | all_children
    all_concepts = set(graph.subjects(RDF.type, SKOS.Concept))
    roots = all_concepts - all_broader

    return sorted(roots, key=str)


# ── Printer ───────────────────────────────────────────────────────────────────

def print_tree(
    graph: Graph,
    children: dict,
    node: URIRef,
    lang: str,
    prefix: str = "",
    is_last: bool = True,
    visited: set = None,
    depth: int = 0,
) -> None:
    if visited is None:
        visited = set()

    connector = "└── " if is_last else "├── "
    label     = get_label(graph, node, lang)
    uri_hint  = GREY(f"  <{node}>") if depth == 0 else ""

    # Colour by depth
    colours = [CYAN, YELLOW, GREEN]
    coloured_label = colours[min(depth, len(colours) - 1)](label)

    print(f"{prefix}{DIM(connector)}{coloured_label}{uri_hint}")

    if node in visited:
        # Cycle guard — note it and stop recursing
        child_prefix = prefix + ("    " if is_last else "│   ")
        print(f"{child_prefix}{DIM('└── ')}{GREY('(already shown)')}")
        return
    visited = visited | {node}

    kids = sorted(children.get(node, []), key=lambda u: get_label(graph, u, lang).lower())
    for i, kid in enumerate(kids):
        last = i == len(kids) - 1
        child_prefix = prefix + ("    " if is_last else "│   ")
        print_tree(graph, children, kid, lang, child_prefix, last, visited, depth + 1)


# ── Scheme metadata ───────────────────────────────────────────────────────────

def print_scheme_info(graph: Graph, lang: str) -> None:
    schemes = list(graph.subjects(RDF.type, SKOS.ConceptScheme))
    if not schemes:
        return
    print(BOLD("\n  Concept Scheme(s):"))
    for scheme in schemes:
        title = get_label(graph, scheme, lang)
        print(f"  {YELLOW(title)}  {GREY(f'<{scheme}>')}")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print the SKOS concept hierarchy of a vocabulary file."
    )
    parser.add_argument("vocab_file", help="Path to the SKOS vocabulary file")
    parser.add_argument(
        "--lang", default="en", help="Preferred language for labels (default: en)"
    )
    args = parser.parse_args()

    # ── Load graph ────────────────────────────────────────────────────────────
    g = Graph()
    try:
        g.parse(args.vocab_file)
    except Exception as exc:
        print(f"ERROR: Could not parse '{args.vocab_file}': {exc}", file=sys.stderr)
        sys.exit(1)

    n_concepts = sum(1 for _ in g.subjects(RDF.type, SKOS.Concept))
    if n_concepts == 0:
        print("WARNING: No skos:Concept triples found in this file.", file=sys.stderr)

    # ── Summary header ────────────────────────────────────────────────────────
    print(BOLD(f"\n{'═' * 60}"))
    print(BOLD(f"  SKOS Concept Hierarchy"))
    print(BOLD(f"  File : {args.vocab_file}"))
    print(BOLD(f"  Lang : {args.lang}   |   Concepts: {n_concepts}"))
    print(BOLD(f"{'═' * 60}"))

    print_scheme_info(g, args.lang)

    # ── Build & print tree ────────────────────────────────────────────────────
    children = build_children(g)
    roots    = find_roots(g, children)

    if not roots:
        print("No top-level concepts found.", file=sys.stderr)
        sys.exit(1)

    for i, root in enumerate(roots):
        last = i == len(roots) - 1
        print_tree(g, children, root, args.lang, prefix="  ", is_last=last)

    print()


if __name__ == "__main__":
    main()
