// [desc] Kanban board frontend — loads cards, renders columns, handles create-and-launch via prompt input [/desc]

let _project = '';
let _pollInterval = null;

function initKanban(project) {
    _project = project;
    loadCards();
    _pollInterval = setInterval(loadCards, 5000);

    document.getElementById('card-desc').addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            createCard();
        }
    });
}

function apiBase() {
    return '/api/kanban/' + encodeURIComponent(_project);
}

function loadCards() {
    fetch(apiBase() + '/cards')
        .then(r => { if (!r.ok) throw new Error('GET cards ' + r.status); return r.json(); })
        .then(cards => renderCards(cards))
        .catch(err => console.error('[kanban] loadCards failed:', err));
}

let showArchived = false;

function toggleArchived() {
    showArchived = !showArchived;
    const btn = document.getElementById('toggle-archived-btn');
    if (btn) btn.textContent = showArchived ? '📦 Masquer les archives' : '📦 Afficher les archives';
    const mainBoard = document.getElementById('kanban-board-main');
    const archSection = document.getElementById('kanban-archives-section');
    const form = document.getElementById('new-card-form');
    if (mainBoard) mainBoard.style.display = showArchived ? 'none' : '';
    if (archSection) archSection.style.display = showArchived ? '' : 'none';
    if (form) form.style.display = showArchived ? 'none' : '';
    loadCards();
}

function renderCards(cards) {
    const colEl = (status) => document.querySelector(`[data-status="${status}"] .kanban-column-cards`);
    const cols = {
        in_progress: colEl('in_progress'),
        awaiting_plan_validation: colEl('awaiting_plan_validation'),
        awaiting_input: colEl('awaiting_input'),
        done: colEl('done'),
        failed: colEl('failed'),
    };

    // Clear columns
    Object.values(cols).forEach(c => { if (c) c.innerHTML = ''; });

    const counts = {};
    Object.keys(cols).forEach(k => counts[k] = 0);

    // Sort done cards by updated_at descending
    const sorted = [...cards].sort((a, b) => {
        if (a.status === 'done' && b.status === 'done') {
            return (b.updated_at || '').localeCompare(a.updated_at || '');
        }
        return 0;
    });

    // Archive board columns
    const archColEl = (status) => document.querySelector(`[data-status="archived-${status}"] .kanban-column-cards`);
    const archCols = {
        in_progress: archColEl('in_progress'),
        awaiting_plan_validation: archColEl('awaiting_plan_validation'),
        awaiting_input: archColEl('awaiting_input'),
        done: archColEl('done'),
        failed: archColEl('failed'),
    };
    Object.values(archCols).forEach(c => { if (c) c.innerHTML = ''; });
    const archCounts = {};
    Object.keys(archCols).forEach(k => archCounts[k] = 0);

    sorted.forEach(card => {
        if (card.archived) {
            // Place archived cards in the archive board columns by status
            const archKey = archCols[card.status] ? card.status : 'done';
            const archCol = archCols[archKey];
            if (!archCol) return;
            archCounts[archKey]++;
            const el = document.createElement('div');
            el.className = 'kanban-card kanban-card-archived';
            el.innerHTML = buildCardHTML(card);
            archCol.appendChild(el);
            return;
        }
        // Skip backlog cards (legacy) — they won't show
        if (card.status === 'backlog') return;
        const colKey = cols[card.status] ? card.status : 'failed';
        const col = cols[colKey];
        if (!col) return;
        counts[colKey]++;
        const el = document.createElement('div');
        el.className = 'kanban-card';
        el.innerHTML = buildCardHTML(card);
        col.appendChild(el);
    });

    // Update archive column counts
    Object.keys(archCounts).forEach(k => {
        const el = document.getElementById('count-archived-' + k);
        if (el) el.textContent = archCounts[k];
    });

    // Update column counts
    Object.keys(counts).forEach(k => {
        const el = document.getElementById('count-' + k);
        if (el) el.textContent = counts[k];
    });
}

function buildCardHTML(card) {
    let badge = '';
    if (card.status !== 'done' && card.status !== 'failed') {
        const labels = {
            in_progress: 'En cours',
            awaiting_plan_validation: 'Plan en attente',
            awaiting_input: 'Question posée'
        };
        badge = `<span class="status-badge ${card.status}">${labels[card.status] || card.status}</span>`;
    }

    let actions = '';
    if (card.agent_id) {
        actions = `<a class="btn btn-secondary" href="/agents/${card.agent_id}">Voir l'agent →</a>`;
        if (card.status === 'awaiting_plan_validation') {
            actions += ` <button class="btn btn-primary" onclick="openPlanModal('${card.id}')">📋 Voir le plan</button>`;
        }
        if (card.status === 'awaiting_input') {
            actions += ` <button class="btn btn-primary" onclick="openQuestionModal('${card.id}')">❓ Voir la question</button>`;
        }
        if (card.status === 'failed') {
            actions += ` <button class="btn btn-primary" onclick="launchCard('${card.id}')">🔄 Relancer</button>`;
        }
    }

    const archiveBtn = card.archived
        ? `<button class="kanban-card-archive" onclick="event.stopPropagation(); unarchiveCard('${card.id}')" title="Désarchiver">📤</button>`
        : `<button class="kanban-card-archive" onclick="event.stopPropagation(); archiveCard('${card.id}')" title="Archiver">📦</button>`;

    return `
        <button class="kanban-card-delete" onclick="event.stopPropagation(); deleteCard('${card.id}')" title="Supprimer">🗑️</button>
        ${archiveBtn}
        ${badge}
        <div class="kanban-card-desc">${escapeHtml(card.description)}</div>
        <div class="kanban-card-actions">${actions}</div>
    `;
}

function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}

function createCard() {
    const input = document.getElementById('card-desc');
    const desc = input.value.trim();
    if (!desc) return;
    input.disabled = true;
    fetch(apiBase() + '/cards', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title: desc.slice(0, 80), description: desc})
    }).then(r => r.json())
      .then(card => {
          // Immediately launch the card
          return fetch(apiBase() + '/cards/' + card.id + '/launch', {method: 'POST'});
      })
      .then(r => {
          input.value = '';
          input.disabled = false;
          input.focus();
          loadCards();
      })
      .catch(() => {
          input.disabled = false;
      });
}

function launchCard(cardId) {
    fetch(apiBase() + '/cards/' + cardId + '/launch', {method: 'POST'})
        .then(r => {
            if (r.ok) loadCards();
            else r.json().then(d => alert(d.error || 'Erreur'));
        });
}

function deleteCard(cardId) {
    if (!confirm('Supprimer ce ticket ?')) return;
    fetch(apiBase() + '/cards/' + cardId, {method: 'DELETE'})
        .then(r => { if (r.ok) loadCards(); });
}

function archiveCard(cardId) {
    fetch(apiBase() + '/cards/' + cardId, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({archived: true})
    }).then(r => { if (r.ok) loadCards(); });
}

function unarchiveCard(cardId) {
    fetch(apiBase() + '/cards/' + cardId, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({archived: false})
    }).then(r => { if (r.ok) loadCards(); });
}

// --- Modal Plan / Question ---

function openPlanModal(cardId) {
    const modal = document.getElementById('kanban-modal');
    const title = document.getElementById('modal-title');
    const body = document.getElementById('modal-body');
    const footer = document.getElementById('modal-footer');
    title.textContent = 'Plan de l\'agent';
    body.innerHTML = '<p class="loading">Chargement…</p>';
    footer.innerHTML = '';
    modal.classList.add('active');

    fetch(apiBase() + '/cards/' + cardId + '/plan')
        .then(r => { if (!r.ok) throw new Error('No plan'); return r.json(); })
        .then(data => {
            body.innerHTML = '<div class="plan-content">' + marked.parse(data.plan_md) + '</div>';
            footer.innerHTML = `
                <button class="btn btn-primary" onclick="acceptPlan('${cardId}')">✅ Accepter le plan</button>
                <button class="btn btn-secondary" onclick="closeModal()">Fermer</button>
            `;
        })
        .catch(() => {
            body.innerHTML = '<p class="empty">Aucun plan disponible.</p>';
            footer.innerHTML = '<button class="btn btn-secondary" onclick="closeModal()">Fermer</button>';
        });
}

function openQuestionModal(cardId) {
    const modal = document.getElementById('kanban-modal');
    const title = document.getElementById('modal-title');
    const body = document.getElementById('modal-body');
    const footer = document.getElementById('modal-footer');
    title.textContent = 'Question de l\'agent';
    body.innerHTML = '<p class="loading">Chargement…</p>';
    footer.innerHTML = '';
    modal.classList.add('active');

    fetch(apiBase() + '/cards/' + cardId + '/question')
        .then(r => { if (!r.ok) throw new Error('No question'); return r.json(); })
        .then(data => {
            let html = '<p class="question-text">' + escapeHtml(data.question) + '</p>';
            if (data.options && data.options.length > 0) {
                html += '<div class="question-options">';
                data.options.forEach((opt, i) => {
                    const label = opt.label || opt;
                    const desc = opt.description ? ' — ' + escapeHtml(opt.description) : '';
                    html += `<button class="btn btn-option" onclick="submitAnswer('${cardId}', '${escapeHtml(label)}')">${escapeHtml(label)}${desc}</button>`;
                });
                html += '</div>';
            }
            if (data.allow_freetext) {
                html += `<div class="question-freetext">
                    <textarea id="answer-input" class="form-input" rows="3" placeholder="Votre réponse…"></textarea>
                </div>`;
            }
            body.innerHTML = html;
            footer.innerHTML = `
                ${data.allow_freetext ? `<button class="btn btn-primary" onclick="submitAnswerFromInput('${cardId}')">📤 Envoyer</button>` : ''}
                <button class="btn btn-secondary" onclick="closeModal()">Fermer</button>
            `;
        })
        .catch(() => {
            body.innerHTML = '<p class="empty">Aucune question en attente.</p>';
            footer.innerHTML = '<button class="btn btn-secondary" onclick="closeModal()">Fermer</button>';
        });
}

function acceptPlan(cardId) {
    fetch(apiBase() + '/cards/' + cardId + '/accept-plan', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({})
    }).then(r => {
        if (r.ok) { closeModal(); loadCards(); }
        else alert('Erreur lors de l\'acceptation du plan');
    });
}

function submitAnswer(cardId, answer) {
    fetch(apiBase() + '/cards/' + cardId + '/answer', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({answer: answer})
    }).then(r => {
        if (r.ok) { closeModal(); loadCards(); }
        else alert('Erreur lors de l\'envoi de la réponse');
    });
}

function submitAnswerFromInput(cardId) {
    const input = document.getElementById('answer-input');
    const answer = input ? input.value.trim() : '';
    if (!answer) { alert('Veuillez entrer une réponse'); return; }
    submitAnswer(cardId, answer);
}

function closeModal() {
    document.getElementById('kanban-modal').classList.remove('active');
}
