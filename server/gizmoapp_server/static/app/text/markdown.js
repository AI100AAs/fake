const SAFE_URL = /^(?:https?:\/\/|mailto:)/i;

function inlineMarkdown(text) {
  const fragment = document.createDocumentFragment();
  const pattern = new RegExp("(\\[[^\\]]+\\]\\(([^\\s)]+)\\)|`([^`]+)`|\\*\\*([^*]+)\\*\\*|__([^_]+)__|\\*([^*]+)\\*|_([^_]+)_)", "g");
  let lastIndex = 0;
  let match;
  while ((match = pattern.exec(text))) {
    if (match.index > lastIndex) fragment.append(document.createTextNode(text.slice(lastIndex, match.index)));
    if (match[1]?.startsWith("[")) {
      const link = document.createElement("a");
      link.textContent = match[1].slice(1, match[1].indexOf("]"));
      link.href = SAFE_URL.test(match[2]) ? match[2] : "#";
      if (link.href !== "#") {
        link.target = "_blank";
        link.rel = "noreferrer";
      }
      fragment.append(link);
    } else if (match[3]) {
      const code = document.createElement("code"); code.textContent = match[3]; fragment.append(code);
    } else {
      const element = document.createElement(match[4] || match[5] ? "strong" : "em");
      element.textContent = match[4] || match[5] || match[6] || match[7];
      fragment.append(element);
    }
    lastIndex = pattern.lastIndex;
  }
  if (lastIndex < text.length) fragment.append(document.createTextNode(text.slice(lastIndex)));
  return fragment;
}

function addInline(parent, text) {
  parent.append(inlineMarkdown(text));
}

export function renderMarkdown(container, source) {
  container.replaceChildren();
  const lines = String(source ?? "").replace(/\r\n?/g, "\n").split("\n");
  let list;
  let code;
  const closeList = () => { if (list) { container.append(list); list = null; } };
  const closeCode = () => { if (code) { const pre = document.createElement("pre"); const codeElement = document.createElement("code"); codeElement.textContent = code.join("\n"); pre.append(codeElement); container.append(pre); code = null; } };

  lines.forEach((line) => {
    if (line.trim().startsWith(String.fromCharCode(96).repeat(3))) { if (code) closeCode(); else { closeList(); code = []; } return; }
    if (code) { code.push(line); return; }
    const item = line.match(/^\s*[-*+]\s+(.+)$/);
    if (item) {
      if (!list) { list = document.createElement("ul"); }
      const li = document.createElement("li"); addInline(li, item[1]); list.append(li); return;
    }
    closeList();
    if (!line.trim()) return;
    const heading = line.match(/^\s*(#{1,3})\s+(.+)$/);
    if (heading) { const element = document.createElement(["h1", "h2", "h3"][heading[1].length - 1]); addInline(element, heading[2]); container.append(element); return; }
    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) { const element = document.createElement("blockquote"); addInline(element, quote[1]); container.append(element); return; }
    const paragraph = document.createElement("p"); addInline(paragraph, line); container.append(paragraph);
  });
  closeList();
  closeCode();
}
