# [desc] Façade du garde-fou de périmètre : doublons entre frères + mandats read-only non tenus. [/desc]
"""Garde-fou de périmètre au dispatch. Voir `review.review_dispatch`."""
from .overlap import OVERLAP_FLAG_KEY, OVERLAP_THRESHOLD, overlapping_siblings
from .readonly import READONLY_FLAG_KEY, declares_read_only, unenforced_read_only
from .review import review_dispatch

__all__ = [
    "OVERLAP_FLAG_KEY", "OVERLAP_THRESHOLD", "READONLY_FLAG_KEY",
    "declares_read_only", "overlapping_siblings", "review_dispatch", "unenforced_read_only",
]
