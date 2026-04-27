"""Working-drawing renderers (BRD Layer 3A).

Deterministic SVG primitives for technical drawings — plan view, sections,
elevations, isometrics. Each module composes shared svg_base helpers
into a CAD-style sheet with title block, scale bar, dimension chains,
and hatch vocabulary.

LLM authoring is layered on top via app.services.<diagram>_drawing_service —
the renderers stay pure / deterministic.
"""
