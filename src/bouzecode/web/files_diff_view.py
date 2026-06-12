# [desc] Builds a self-contained HTML page showing all file diffs from a session with Monaco editors. [/desc]
# [desc] Builds the self-contained HTML page that shows all file diffs from a session.
"""Render the edited-files page (diff list + Monaco side-by-side viewers)."""
from __future__ import annotations

import html
import os

from .html_renderer.renderer import _guess_language, _json_script_safe, _render_diff_text


_FILES_CSS = """\
*,*::before,*::after{box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;max-width:960px;margin:0 auto;
  padding:1.5rem;background:#f5f7fa;color:#1f2328;line-height:1.6}
.file-list{list-style:none;padding:0;margin:0 0 1rem 0}
.file-item{margin:.5rem 0}
.file-link{display:inline-flex;align-items:center;gap:.5rem;padding:.4rem .8rem;
  border-radius:6px;text-decoration:none;color:#0969da;font-family:ui-monospace,monospace;
  font-size:.88rem;font-weight:500;transition:background .15s}
.file-link:hover{background:#dbeafe}
.file-link .badge{font-size:.7rem;padding:1px 6px;border-radius:9999px;font-weight:600;
  font-family:system-ui,sans-serif;text-transform:uppercase}
.badge-new{background:#dafbe1;color:#1a7f37}
.badge-modified{background:#fff8c5;color:#9a6700}
details.file-diff{margin:.75rem 0;border:1px solid #d1d9e0;border-radius:8px;
  background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.06)}
details.file-diff>summary{padding:.6rem 1rem;cursor:pointer;font-weight:600;
  font-family:ui-monospace,monospace;font-size:.88rem;border-radius:8px;
  list-style:none;display:flex;align-items:center;gap:.5rem;color:#1f2328}
details.file-diff>summary::-webkit-details-marker{display:none}
details.file-diff>summary .chevron{margin-left:auto;transition:transform .2s;color:#888;font-size:.7em}
details.file-diff[open]>summary .chevron{transform:rotate(90deg)}
details.file-diff[open]>summary{border-bottom:1px solid #d1d9e0;border-radius:8px 8px 0 0}
.diff-body{padding:.5rem;overflow-x:auto}
.monaco-diff-box{border:1px solid #d1d9e0;border-radius:6px;overflow:hidden;margin:.5rem 0}
.diff-fallback{margin:0;border:none;box-shadow:none;border-radius:0}
.diff-line{font-family:ui-monospace,monospace;white-space:pre;font-size:.82rem;
  padding:1px 8px;display:block}
.diff-add{background:#dafbe1;color:#1a7f37}.diff-del{background:#ffebe9;color:#cf222e}
.diff-hdr{color:#656d76;font-style:italic}
.diff{font-family:ui-monospace,monospace;font-size:.82rem}
.empty{color:#888;padding:3rem;text-align:center;font-style:italic}
.summary-bar{background:#f0f3f6;border:1px solid #d1d9e0;border-radius:8px;
  padding:.75rem 1rem;margin-bottom:1.25rem;font-size:.9rem;color:#656d76}
.summary-bar strong{color:#1f2328}
"""

_MONACO_CDN = "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.0/min"


def empty_page() -> str:
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<style>{_FILES_CSS}</style></head>'
        '<body><p class="empty">Aucun fichier modifie dans cette session</p></body></html>'
    )


def build_page(snapshots: dict) -> str:
    sorted_paths = sorted(snapshots.keys())
    new_count = sum(1 for s in snapshots.values() if s.get("is_new"))
    mod_count = len(snapshots) - new_count

    parts = [
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">',
        f'<style>{_FILES_CSS}</style></head><body>',
    ]

    summary_parts = [f'<strong>{len(snapshots)}</strong> fichier{"s" if len(snapshots) > 1 else ""}']
    if new_count:
        summary_parts.append(f'{new_count} nouveau{"x" if new_count > 1 else ""}')
    if mod_count:
        summary_parts.append(f'{mod_count} modifie{"s" if mod_count > 1 else ""}')
    parts.append(f'<div class="summary-bar">{" &mdash; ".join(summary_parts)}</div>')

    parts.append('<ul class="file-list">')
    for fp in sorted_paths:
        snap = snapshots[fp]
        badge_cls = "badge-new" if snap.get("is_new") else "badge-modified"
        badge_text = "new" if snap.get("is_new") else "mod"
        anchor = f"file-{hash(fp) & 0xFFFFFFFF:08x}"
        parts.append(
            f'<li class="file-item"><a class="file-link" href="#{anchor}">'
            f'<span class="badge {badge_cls}">{badge_text}</span> {html.escape(fp)}'
            f'</a></li>'
        )
    parts.append('</ul>')

    diffs_data = []
    for idx, fp in enumerate(sorted_paths):
        snap = snapshots[fp]
        before = snap.get("before", "")
        after = snap.get("after", "")
        anchor = f"file-{hash(fp) & 0xFFFFFFFF:08x}"
        badge_cls = "badge-new" if snap.get("is_new") else "badge-modified"
        badge_text = "NEW" if snap.get("is_new") else "MOD"

        fallback_html = _render_diff_text(before, after)
        lang = _guess_language(fp)
        n_lines = max(before.count("\n"), after.count("\n")) + 1
        height = min(500, max(120, n_lines * 22 + 40))
        diff_id = f"bz-fdiff-{idx}"

        diffs_data.append({
            "id": diff_id, "lang": lang,
            "original": before, "modified": after,
        })

        parts.append(
            f'<details class="file-diff" id="{anchor}" open>'
            f'<summary><span class="badge {badge_cls}">{badge_text}</span> '
            f'{html.escape(fp)}<span class="chevron">&#9654;</span></summary>'
            f'<div class="diff-body">'
            f'<div id="{diff_id}" class="monaco-diff-box" style="height:{height}px">'
            f'<div class="diff-fallback">{fallback_html}</div>'
            f'</div></div></details>'
        )

    parts.append('<script>window.__bz_diffs=[')
    for d in diffs_data:
        parts.append(
            f'{{id:{_json_script_safe(d["id"])},'
            f'lang:{_json_script_safe(d["lang"])},'
            f'original:{_json_script_safe(d["original"])},'
            f'modified:{_json_script_safe(d["modified"])}}},'
        )
    parts.append('];</script>')
    parts.append(
        f'<script src="{_MONACO_CDN}/vs/loader.js"></script>'
        '<script>'
        'if(window.__bz_diffs&&window.__bz_diffs.length){'
        f'  require.config({{paths:{{vs:"{_MONACO_CDN}/vs"}}}});'
        '  require(["vs/editor/editor.main"],function(){'
        '    var map={};'
        '    window.__bz_diffs.forEach(function(d){map[d.id]=d});'
        '    function initDiff(el,d){'
        '      var fb=el.querySelector(".diff-fallback");if(fb)fb.remove();'
        '      var ed=monaco.editor.createDiffEditor(el,{'
        '        readOnly:true,renderSideBySide:true,'
        '        minimap:{enabled:false},scrollBeyondLastLine:false,'
        '        automaticLayout:true,fontSize:13,lineNumbers:"off"'
        '      });'
        '      ed.setModel({'
        '        original:monaco.editor.createModel(d.original,d.lang),'
        '        modified:monaco.editor.createModel(d.modified,d.lang)'
        '      });'
        '    }'
        '    var obs=new IntersectionObserver(function(entries){'
        '      entries.forEach(function(e){'
        '        if(!e.isIntersecting)return;'
        '        var d=map[e.target.id];'
        '        if(d&&!d.done){d.done=true;obs.unobserve(e.target);initDiff(e.target,d);}'
        '      });'
        '    },{threshold:0.01});'
        '    window.__bz_diffs.forEach(function(d){'
        '      var el=document.getElementById(d.id);'
        '      if(el)obs.observe(el);'
        '    });'
        '  });'
        '}'
        '</script>'
    )

    parts.append('</body></html>')
    return '\n'.join(parts)
