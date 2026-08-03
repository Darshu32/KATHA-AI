"""KATHA spatial engine — the geometry-as-truth render path.

The LLM emits a spec (``DesignGraph``); this package turns that spec into real
geometry and a real render, so the image is a *function of the spec*, never a
text-to-image guess:

    kernel      spec → deterministic solids (Manifold booleans)
    rasterizer  solids → base + depth + normal + exact hotspots (real camera)
    finish      base + depth → photoreal, obeying the geometry (downstream only)
    render_pipeline  orchestrates the three into one call for the generator

This replaces Gemini-as-core, the box glTF render reference, and the vision
object-grounding hack (hotspots are now exact camera projections).
"""

from app.services.spatial.render_pipeline import RenderResult, render_design

__all__ = ["render_design", "RenderResult"]
