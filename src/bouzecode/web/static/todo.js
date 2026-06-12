// [desc] Notepad auto-save with 1s debounce for per-project TODO notes via REST API [/desc]

(function() {
    var container = document.querySelector('.todo-container');
    var project = container.getAttribute('data-project');
    var editor = document.getElementById('todo-editor');
    var status = document.getElementById('save-status');
    var timer = null;

    editor.addEventListener('input', function() {
        status.textContent = '⏳ Unsaved changes';
        status.className = 'todo-status saving';
        if (timer) clearTimeout(timer);
        timer = setTimeout(save, 1000);
    });

    function save() {
        var content = editor.value;
        status.textContent = '💾 Saving...';
        status.className = 'todo-status saving';
        fetch('/api/todo/' + encodeURIComponent(project), {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({content: content})
        }).then(function(r) {
            if (r.ok) {
                status.textContent = '✓ Saved';
                status.className = 'todo-status saved';
            } else {
                status.textContent = '✗ Save failed';
                status.className = 'todo-status';
            }
        }).catch(function() {
            status.textContent = '✗ Save failed';
            status.className = 'todo-status';
        });
    }
})();
