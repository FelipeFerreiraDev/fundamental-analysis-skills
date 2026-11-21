"""Ingestion (`sync`) from free public sources into the local warehouse.

Phase 1: CVM (DFP, ITR, cadastro), B3 COTAHIST, BCB SGS, brapi. Downloads are filtered to the
companies being analyzed, normalized, loaded and then discarded (docs/architecture.md §7).
"""
