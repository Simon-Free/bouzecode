// [desc] Per-LLM-call context breakdown: flat list of every object sent, with char-based token estimate and cached/new-cache/fresh badge [/desc]
/* Context Viewer — per-LLM-call object-by-object breakdown */
(function() {
    const D = window.__CTX;
    if (!D || !D.calls || !D.calls.length) {
        document.getElementById('app').innerHTML = '<div class="ctx-empty">No LLM calls in this session</div>';
        return;
    }

    let cur = D.calls.length;

    const esc = s => {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    };
    const fmt = n => n ? n.toLocaleString() : '0';

    const STATUS_LABEL = {
        'cached': 'CACHED', 'new-cache': 'NEW-CACHE', 'fresh': 'FRESH',
    };
    const GC_ICON = {
        'stable': '', 'live': '', 'verbatim': '\u{1F4D7}',
        'snippet': '\u{1F4D9}', 'trashed': '\u{1F5D1}', 'xml-compacted': '\u{25AB}',
    };
    const KIND_ICON = {
        'system': '\u{2699}', 'notes_block': '\u{1F4DD}',
        'user': '\u{1F464}', 'assistant': '\u{1F916}',
        'tool_result': '\u{1F527}',
    };

    function renderCacheBar(call) {
        const cached = call.tokens_by_status['cached'] || 0;
        const newCache = call.tokens_by_status['new-cache'] || 0;
        const fresh = call.tokens_by_status['fresh'] || 0;
        const total = cached + newCache + fresh || 1;
        const cPct = (cached / total * 100).toFixed(1);
        const nPct = (newCache / total * 100).toFixed(1);
        const fPct = (fresh / total * 100).toFixed(1);
        return `<div class="cache-bar">
            <div class="cb-seg cb-cached" style="width:${cPct}%" title="Cached: ${fmt(cached)} tk">${cPct > 8 ? fmt(cached) + ' tk' : ''}</div>
            <div class="cb-seg cb-new" style="width:${nPct}%" title="New-cache: ${fmt(newCache)} tk">${nPct > 8 ? fmt(newCache) + ' tk' : ''}</div>
            <div class="cb-seg cb-fresh" style="width:${fPct}%" title="Fresh: ${fmt(fresh)} tk">${fPct > 8 ? fmt(fresh) + ' tk' : ''}</div>
        </div>`;
    }

    function renderItem(item) {
        const gcIcon = GC_ICON[item.gc_status] || '';
        const kIcon = KIND_ICON[item.kind] || '';
        const preview = item.preview ? esc(item.preview.substring(0, 220)) : '';
        const gcBadge = item.gc_status && ['trashed', 'snippet', 'xml-compacted'].includes(item.gc_status)
            ? `<span class="gc-badge gc-${item.gc_status}">${gcIcon} ${item.gc_status}</span>` : '';
        const nTools = item.n_tools ? `<span class="n-tools">${item.n_tools} tools</span>` : '';
        const idxLabel = item.payload_idx == null ? '\u2014' : item.payload_idx;
        return `<tr class="ctx-row status-${item.cache_status}">
            <td class="c-idx">${idxLabel}</td>
            <td class="c-kind"><span class="kind-icon">${kIcon}</span>${esc(item.kind)}</td>
            <td class="c-label"><div class="label-main">${esc(item.label)}</div>
                ${preview ? `<div class="label-preview">${preview}</div>` : ''}
                ${nTools}${gcBadge}</td>
            <td class="c-tokens">${fmt(item.est_tokens)}</td>
            <td class="c-cache"><span class="cache-pill cache-${item.cache_status}">${STATUS_LABEL[item.cache_status] || ''}</span></td>
        </tr>`;
    }

    function renderCall() {
        const call = D.calls[cur - 1];
        const items = call.items;
        const estTotal = Object.values(call.tokens_by_status).reduce((a, b) => a + b, 0);

        let html = `<div class="ctx-header">
            <span class="ctx-title"><a href="javascript:history.back()">&#8592;</a> Context Viewer &mdash; ${esc(D.session_id)}</span>
            <div class="ctx-nav">
                <button id="prev" ${cur <= 1 ? 'disabled' : ''}>&larr; Prev</button>
                <input type="range" class="ctx-slider" id="slider" min="1" max="${D.calls.length}" value="${cur}">
                <button id="next" ${cur >= D.calls.length ? 'disabled' : ''}>Next &rarr;</button>
            </div>
            <span class="ctx-turn-label">LLM call ${cur} / ${D.calls.length} &middot; turn ${call.turn}</span>
            <span class="ctx-prompt-preview">${esc((call.user_prompt || '').substring(0, 140))}</span>
        </div>`;

        html += `<div class="ctx-stats">
            <div class="ctx-stat accent"><span class="val">${fmt(call.api_input_tokens)}</span> API input</div>
            <div class="ctx-stat"><span class="val">${fmt(call.api_cache_read)}</span> API cache read</div>
            <div class="ctx-stat"><span class="val">${fmt(call.api_cache_create)}</span> API cache create</div>
            <div class="ctx-stat"><span class="val">${fmt(call.api_output_tokens)}</span> API output</div>
            <div class="ctx-stat" style="margin-left:auto"><span class="val">${fmt(estTotal)}</span> est total (chars/3.5)</div>
            <div class="ctx-stat"><span class="val">${items.length}</span> objects</div>
        </div>`;

        html += `<div class="ctx-bar-wrap">
            <div class="ctx-bar-label">Estimated breakdown of prefix sent:</div>
            ${renderCacheBar(call)}
            <div class="ctx-bar-legend">
                <span><span class="dot dot-cached"></span> cached (prefix of prev call, byte-for-byte match)</span>
                <span><span class="dot dot-new"></span> new-cache (cached this call, reused next)</span>
                <span><span class="dot dot-fresh"></span> fresh (recomputed every iteration)</span>
            </div>
        </div>`;

        html += `<div class="ctx-table-wrap"><table class="ctx-table"><thead><tr>
            <th title="Position in the on-wire payload (\u2014 = synthetic, not a message)">payload #</th>
            <th>Kind</th><th>Label / brief</th><th>Est tk</th><th>Cache</th>
        </tr></thead><tbody>`;
        for (const item of items) {
            html += renderItem(item);
        }
        html += `</tbody></table></div>`;

        document.getElementById('app').innerHTML = html;
        bindEvents();
    }

    function goTo(n) {
        cur = Math.max(1, Math.min(D.calls.length, n));
        renderCall();
    }

    function bindEvents() {
        const prev = document.getElementById('prev');
        const next = document.getElementById('next');
        const slider = document.getElementById('slider');
        if (prev) prev.onclick = () => goTo(cur - 1);
        if (next) next.onclick = () => goTo(cur + 1);
        if (slider) slider.oninput = e => goTo(parseInt(e.target.value));
        document.querySelectorAll('.ctx-row').forEach(row => {
            row.onclick = () => row.classList.toggle('expanded');
        });
    }

    document.addEventListener('keydown', e => {
        if (e.key === 'ArrowLeft') goTo(cur - 1);
        else if (e.key === 'ArrowRight') goTo(cur + 1);
    });

    renderCall();
})();
