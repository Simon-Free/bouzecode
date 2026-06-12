// [desc] Page fichiers: racine par projet, arborescence lazy, contenu coloré pygments. [/desc]
"use strict";

const rootSelect = document.getElementById("root-select");

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function rootParam() {
  return rootSelect.value ? `&root=${encodeURIComponent(rootSelect.value)}` : "";
}

async function fetchEntries(path) {
  const response = await fetch(`/api/files/tree?path=${encodeURIComponent(path)}${rootParam()}`);
  if (!response.ok) return [];
  return (await response.json()).entries;
}

function entryNode(entry) {
  const wrapper = el("div", "tree-item");
  const label = el("div", entry.dir ? "tree-dir" : "tree-file",
    (entry.dir ? "▸ " : "") + entry.name);
  wrapper.appendChild(label);
  if (entry.dir) {
    const children = el("div", "tree-children");
    children.hidden = true;
    let loaded = false;
    label.addEventListener("click", async () => {
      if (!loaded) {
        loaded = true;
        (await fetchEntries(entry.path)).forEach((child) => children.appendChild(entryNode(child)));
      }
      children.hidden = !children.hidden;
      label.textContent = (children.hidden ? "▸ " : "▾ ") + entry.name;
    });
    wrapper.appendChild(children);
  } else {
    label.addEventListener("click", () => openFile(entry.path, label));
  }
  return wrapper;
}

let monacoEditor = null;

function showInMonaco(monaco, viewer, data, path) {
  let box = document.getElementById("monaco-file-box");
  if (!box) {
    box = el("div");
    box.id = "monaco-file-box";
    viewer.replaceChildren(box);
    monacoEditor = monaco.editor.create(box, {
      readOnly: true, theme: "vs-dark", automaticLayout: true,
      minimap: { enabled: false }, scrollBeyondLastLine: false,
    });
  } else if (!viewer.contains(box)) {
    viewer.replaceChildren(box);
  }
  monacoEditor.setModel(
    monaco.editor.createModel(data.content, monacoLanguage(path)));
}

async function openFile(path, label) {
  document.querySelectorAll(".tree-file.selected").forEach((node) => node.classList.remove("selected"));
  label.classList.add("selected");
  const response = await fetch(`/api/files/content?path=${encodeURIComponent(path)}&hl=1${rootParam()}`);
  const data = await response.json();
  const header = document.getElementById("file-path");
  const viewer = document.getElementById("file-content");
  if (data.error || data.binary) {
    viewer.replaceChildren();
    header.textContent = data.error || `${path} — fichier binaire (${data.size} octets)`;
    return;
  }
  header.textContent = `${path} — ${data.size} octets${data.truncated ? " (tronqué)" : ""}`;
  const monaco = await loadMonaco();
  if (monaco) {
    showInMonaco(monaco, viewer, data, path);
    return;
  }
  viewer.replaceChildren();
  if (data.html) {
    viewer.innerHTML = data.html;
  } else {
    const pre = el("pre", "code");
    pre.textContent = data.content;
    viewer.appendChild(pre);
  }
}

async function loadTree() {
  const tree = document.getElementById("file-tree");
  tree.replaceChildren();
  (await fetchEntries("")).forEach((entry) => tree.appendChild(entryNode(entry)));
}

rootSelect.addEventListener("change", loadTree);
loadTree();
