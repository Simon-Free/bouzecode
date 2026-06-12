// [desc] Client-side live updates for the agent detail page (status tag, action buttons, spinners, question box) via SSE. [/desc]
(function () {
    var config = document.getElementById('agentConfig');
    if (!config) return;
    var sessionUrl = config.dataset.sessionUrl;
    var streamUrl = config.dataset.streamUrl;
    var stdoutOffset = parseInt(config.dataset.stdoutOffset || '0', 10);
    var isRunning = config.dataset.running === '1';

    var badge = document.getElementById('ipcBadge');
    var statusTag = document.getElementById('statusTag');
    var killForm = document.getElementById('killForm');
    var killButton = document.getElementById('killButton');
    var resumeForm = document.getElementById('resumeForm');
    var rawPanel = document.getElementById('panel-raw');
    var frame = document.getElementById('sessionFrame');
    var planFrame = document.getElementById('planFrame');
    var filesFrame = document.getElementById('filesFrame');
    var promptInput = document.getElementById('promptInput');
    var questionBox = document.getElementById('questionBox');
    var questionText = document.getElementById('questionText');
    var optionsList = document.getElementById('optionsList');
    var lastSessionMtime = null;

    function renderStatusTag(data) {
        if (data.ipc_status === 'running' && data.running) {
            statusTag.innerHTML = '<span class="tag running"><span class="spinner-inline"></span>running</span>';
        } else if (data.ipc_status === 'awaiting_input') {
            statusTag.innerHTML = '<span class="tag" style="background:#cce5ff;color:#004085">awaiting input</span>';
        } else if (data.returncode !== null && data.returncode < 0) {
            statusTag.innerHTML = '<span class="tag" style="background:#f8d7da;color:#721c24">crashed (rc=' + data.returncode + ')</span>';
        } else {
            var rc = (data.returncode !== null && data.returncode !== undefined) ? data.returncode : '---';
            statusTag.innerHTML = '<span class="tag done">rc=' + rc + '</span>';
        }
    }

    function renderActionButtons(data) {
        var showKill = data.running || data.ipc_status === 'awaiting_input';
        if (killForm) {
            killForm.style.display = showKill ? 'inline' : 'none';
            if (killButton) {
                killButton.textContent = (data.ipc_status === 'awaiting_input') ? 'Abandonner la question' : 'Kill';
            }
        }
        if (resumeForm) {
            resumeForm.style.display = (!showKill) ? 'inline' : 'none';
        }
    }

    function renderRunIndicator(data) {
        var indicator = document.getElementById('runIndicator');
        if (data.running) {
            if (!indicator && rawPanel) {
                indicator = document.createElement('div');
                indicator.id = 'runIndicator';
                indicator.className = 'running-indicator';
                indicator.innerHTML = '<span class="spinner-inline"></span> Agent en cours d\'execution...';
                rawPanel.insertBefore(indicator, rawPanel.firstChild);
            }
        } else if (indicator) {
            indicator.remove();
        }
    }

    function refreshSessionIframe() {
        var doc, atBottom = true, scrollPos = 0;
        try {
            doc = frame.contentDocument || frame.contentWindow.document;
            scrollPos = doc.documentElement.scrollTop || doc.body.scrollTop;
            var sh = doc.documentElement.scrollHeight;
            var ch = doc.documentElement.clientHeight;
            atBottom = (sh - scrollPos - ch) < 100;
        } catch (e) { /* cross-origin or not yet loaded */ }
        frame.onload = function () {
            try {
                var d = frame.contentDocument || frame.contentWindow.document;
                d.documentElement.scrollTop = atBottom ? d.documentElement.scrollHeight : scrollPos;
            } catch (e) { /* ignore cross-origin errors */ }
            frame.onload = null;
        };
        frame.src = sessionUrl + '?_t=' + Date.now();
    }

    function updatePlaceholder(status) {
        if (status === 'awaiting_input') promptInput.placeholder = 'Votre reponse...';
        else if (status === 'running') promptInput.placeholder = 'Interrompre et envoyer...';
        else if (status === 'idle') promptInput.placeholder = 'Continuer la conversation...';
        else promptInput.placeholder = 'Relancer la conversation...';
    }

    function updateQuestionBox(data) {
        var isAwaiting = (data.ipc_status === 'awaiting_input' || data.ipc_status === 'awaiting_plan_validation');
        if (isAwaiting && data.question) {
            questionText.textContent = data.question;
            questionBox.classList.remove('hidden');
            optionsList.innerHTML = '';
            var opts = data.options || [];
            if (typeof opts === 'string') {
                try { opts = JSON.parse(opts); } catch(e) { opts = []; }
            }
            opts.forEach(function (opt) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.textContent = opt.label || opt;
                btn.onclick = function () {
                    promptInput.value = btn.textContent;
                    promptInput.closest('form').submit();
                };
                optionsList.appendChild(btn);
            });
        } else {
            questionBox.classList.add('hidden');
        }
    }

    function updateUI(data) {
        badge.textContent = data.ipc_status;
        badge.className = 'status-badge ' + data.ipc_status;
        renderStatusTag(data);
        renderActionButtons(data);
        renderRunIndicator(data);
        updatePlaceholder(data.ipc_status);
        updateQuestionBox(data);

        if (data.session_mtime != null) {
            if (lastSessionMtime !== null && data.session_mtime !== lastSessionMtime) {
                refreshSessionIframe();
                planFrame.src = planFrame.src;
                filesFrame.src = filesFrame.src;
            }
            lastSessionMtime = data.session_mtime;
        }
    }

    if (isRunning) {
        var pre = document.getElementById('stdout');
        var source = new EventSource(streamUrl + '?offset=' + stdoutOffset);
        source.onmessage = function (event) {
            pre.innerHTML += event.data + '\n';
            pre.scrollTop = pre.scrollHeight;
        };
        source.addEventListener('state', function (event) {
            updateUI(JSON.parse(event.data));
        });
        source.addEventListener('done', function () {
            source.close();
            refreshSessionIframe();
        });
    }
})();

window.switchTab = function (name) {
    document.querySelectorAll('.tab-btn').forEach(function (btn) {
        btn.classList.toggle('active', btn.dataset.tab === name);
    });
    document.querySelectorAll('.tab-panel').forEach(function (p) {
        p.classList.toggle('active', p.id === 'panel-' + name);
    });
};
