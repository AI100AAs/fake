let knowledgeEntries = [];

function claimTerms(text) {
  return new Set((text.toLowerCase().match(/[a-z]{4,}/g) || []).filter((word) => !["about", "after", "because", "could", "from", "have", "into", "more", "that", "their", "these", "this", "with"].includes(word)));
}

function crossReferences(claim) {
  const terms = claimTerms(claim);
  return knowledgeEntries.map((entry) => {
    const matchedTerms = [...claimTerms(`${entry.title} ${entry.notes}`)].filter((term) => terms.has(term));
    return { entry, matchedTerms };
  }).filter((match) => match.matchedTerms.length >= 2).sort((a, b) => b.matchedTerms.length - a.matchedTerms.length).slice(0, 3);
}

function analyze(text, sourceUrl = "") {
  const words = text.trim().split(/\s+/).filter(Boolean);
  const lower = text.toLowerCase();
  const sensational = ["shocking", "miracle", "they don't want you to know", "100%", "everyone", "breaking"].filter((word) => lower.includes(word));
  const hedges = ["may", "could", "suggests", "promising", "according to", "researchers say"].filter((word) => lower.includes(word));
  const sourceCue = /study|research|report|data|university|researchers|according to/.test(lower);
  const score = Math.max(18, Math.min(94, 54 + (sourceCue ? 18 : 0) + hedges.length * 4 - sensational.length * 15 - (words.length < 18 ? 10 : 0)));
  const label = score >= 76 ? "Promising signal" : score >= 52 ? "Needs verification" : "High-risk signal";
  const claims = text.split(/[.!?]+/).map((part) => part.trim()).filter((part) => part.length > 24).slice(0, 3).map((claim) => ({
    claim,
    assessment: sourceCue ? "mixed" : "unclear",
    evidence: sourceCue ? "The article uses a source or research cue, but the underlying evidence still needs to be checked directly." : "This statement appears in the submitted text, but no independent supporting evidence was provided.",
    sources: sourceUrl ? [{ title: "Article analyzed", url: sourceUrl, relevance: "Primary article containing this claim" }] : [],
  }));
  const signals = [];
  if (sourceCue) signals.push(["context", "A source or research cue is present", "positive"]);
  if (hedges.length) signals.push(["language", "Some uncertainty is acknowledged", "positive"]);
  if (sensational.length) signals.push(["framing", "Emotionally loaded wording may amplify the claim", "caution"]);
  if (!sourceCue) signals.push(["evidence", "No clear source cue found; verify the original evidence", "caution"]);
  if (!claims.length) claims.push({ claim: text.trim().slice(0, 180), assessment: "unclear", evidence: "The text did not contain a longer sentence that could be separated reliably. Check the original context and supporting sources.", sources: sourceUrl ? [{ title: "Article analyzed", url: sourceUrl, relevance: "Primary article containing this claim" }] : [] });
  return { score, label, claims, signals, summary: score >= 76 ? "The wording includes useful evidence cues and measured language." : score >= 52 ? "There are useful cues, but key claims still need source-level checking." : "Strong framing or thin evidence cues make this worth checking before sharing." };
}

function renderReport(report) {
  document.querySelector("#empty-report").hidden = true;
  document.querySelector("#report-content").hidden = false;
  document.querySelector("#score-value").textContent = report.score;
  document.querySelector("#score-label").textContent = report.label;
  document.querySelector("#score-summary").textContent = report.summary;
  document.querySelector("#score-ring").style.setProperty("--score", `${report.score * 3.6}deg`);
  document.querySelector("#claim-count").textContent = `${report.claims.length} found`;
  document.querySelector("#claim-list").replaceChildren(...report.claims.map((item) => {
    const claim = typeof item === "string" ? { claim: item, assessment: "unclear", evidence: "No claim-level evidence was returned for this earlier analysis.", sources: [] } : item;
    const article = document.createElement("article");
    article.className = "claim-card";
    const heading = document.createElement("div"); heading.className = "claim-heading";
    const title = document.createElement("strong"); title.textContent = claim.claim;
    const assessment = document.createElement("span"); assessment.className = `assessment ${["supported", "mixed", "unsupported"].includes(claim.assessment) ? claim.assessment : "unclear"}`; assessment.textContent = claim.assessment || "unclear";
    heading.append(title, assessment);
    const evidenceLabel = document.createElement("small"); evidenceLabel.className = "evidence-label"; evidenceLabel.textContent = "Evidence and context";
    const evidence = document.createElement("p"); evidence.className = "claim-evidence"; evidence.textContent = claim.evidence || "No evidence explanation was provided.";
    const sources = document.createElement("div"); sources.className = "claim-sources";
    (Array.isArray(claim.sources) ? claim.sources : []).forEach((source) => {
      if (!source || typeof source.url !== "string" || !(source.url.startsWith("http://") || source.url.startsWith("https://"))) return;
      const link = document.createElement("a"); link.href = source.url; link.target = "_blank"; link.rel = "noreferrer"; link.textContent = source.title || source.url; link.title = source.relevance || "Source"; sources.append(link);
    });
    if (!sources.children.length) { const none = document.createElement("span"); none.textContent = "No independent source supplied"; sources.append(none); }
    const references = document.createElement("div"); references.className = "claim-references";
    const referenceMatches = crossReferences(claim.claim);
    if (referenceMatches.length) {
      const referenceLabel = document.createElement("small"); referenceLabel.textContent = "Knowledge-base cross-reference"; references.append(referenceLabel);
      referenceMatches.forEach(({ entry, matchedTerms }) => {
        const reference = document.createElement("div"); reference.className = "reference-match";
        const referenceTitle = document.createElement("strong"); referenceTitle.textContent = entry.title;
        const referenceTerms = document.createElement("span"); referenceTerms.textContent = `matches: ${matchedTerms.slice(0, 4).join(", ")}`;
        reference.append(referenceTitle, referenceTerms);
        if (entry.source_url) { const link = document.createElement("a"); link.href = entry.source_url; link.target = "_blank"; link.rel = "noreferrer"; link.textContent = "Open source"; reference.append(link); }
        references.append(reference);
      });
    }
    article.append(heading, evidenceLabel, evidence, sources, references);
    return article;
  }));
  document.querySelector("#signal-list").replaceChildren(...report.signals.map((signal) => {
    const div = document.createElement("div");
    div.className = `signal ${signal.tone === "caution" ? "caution" : "positive"}`;
    const kind = document.createElement("span"); kind.textContent = signal.kind;
    const text = document.createElement("p"); text.textContent = signal.text;
    div.append(kind, text);
    return div;
  }));
}

function renderHistoryItem(item, onSelect) {
  const button = document.createElement("button");
  button.className = "history-item";
  button.type = "button";
  const title = document.createElement("strong");
  title.textContent = item.source_url || item.article_text.slice(0, 100);
  const meta = document.createElement("span");
  const date = new Date(`${item.created_at.replace(" ", "T")}Z`);
  meta.textContent = `${item.input_type === "url" ? "LINK" : "TEXT"} · ${Number.isNaN(date.getTime()) ? item.created_at : date.toLocaleString()}`;
  const score = document.createElement("b");
  const report = JSON.parse(item.report_json);
  score.textContent = `${report.score}/100`;
  button.append(title, meta, score);
  button.addEventListener("click", () => onSelect(item, report));
  return button;
}

function bootstrap() {
  const runtime = window.GizmoAppRuntime;
  if (!runtime) {
    throw new Error("The shared app runtime did not load.");
  }
  const config = runtime.readConfig();
  const input = document.querySelector("#article-input");
  const count = document.querySelector("#char-count");
  const reportState = document.querySelector("#report-state");
  const themeToggle = document.querySelector("#theme-toggle");
  const historyList = document.querySelector("#history-list");
  const historyEmpty = document.querySelector("#history-empty");
  const historyState = document.querySelector("#history-state");
  const knowledgeList = document.querySelector("#knowledge-list");
  const knowledgeEmpty = document.querySelector("#knowledge-empty");
  const knowledgeState = document.querySelector("#knowledge-state");
  const chatMessages = document.querySelector("#chat-messages");
  const chatState = document.querySelector("#chat-state");
  const chatInput = document.querySelector("#chat-input");
  const chatSubmit = document.querySelector("#chat-submit");
  const setTheme = (dark) => {
    document.documentElement.classList.toggle("dark-mode", dark);
    themeToggle.setAttribute("aria-pressed", String(dark));
    themeToggle.innerHTML = `<span aria-hidden="true">${dark ? "☀" : "☾"}</span> ${dark ? "Light mode" : "Dark mode"}`;
  };
  try { setTheme(window.localStorage.getItem("signalcheck-theme") === "dark"); } catch { setTheme(false); }
  themeToggle.addEventListener("click", () => {
    const dark = !document.documentElement.classList.contains("dark-mode");
    setTheme(dark);
    try { window.localStorage.setItem("signalcheck-theme", dark ? "dark" : "light"); } catch { /* Storage is optional in previews. */ }
  });
  const render = () => { count.textContent = `${input.value.length.toLocaleString()} characters`; };
  input.addEventListener("input", render);
  const loadHistory = async () => {
    try {
      const response = await fetch(`${config.apiBase}/history`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.errors?.[0] || "History could not be loaded.");
      historyList.replaceChildren(...payload.history.map((item) => renderHistoryItem(item, (selected, report) => {
        input.value = selected.article_text;
        render();
        renderReport(report);
        reportState.textContent = "Previous analysis restored";
        input.focus();
      })));
      historyEmpty.hidden = payload.history.length > 0;
      historyState.textContent = payload.history.length ? `${payload.history.length} saved` : "No saved checks";
    } catch (error) {
      historyState.textContent = error.message;
      historyEmpty.hidden = false;
    }
  };
  const renderKnowledge = () => {
    knowledgeList.replaceChildren(...knowledgeEntries.map((entry) => {
      const card = document.createElement("article"); card.className = "knowledge-card";
      const title = document.createElement("strong"); title.textContent = entry.title;
      const notes = document.createElement("p"); notes.textContent = entry.notes;
      const footer = document.createElement("div"); footer.className = "knowledge-meta";
      if (entry.source_url) { const link = document.createElement("a"); link.href = entry.source_url; link.target = "_blank"; link.rel = "noreferrer"; link.textContent = "Open source"; footer.append(link); }
      const remove = document.createElement("button"); remove.type = "button"; remove.className = "remove-reference"; remove.textContent = "Remove"; remove.addEventListener("click", async () => {
        await fetch(`${config.apiBase}/knowledge-base/${entry.id}`, { method: "DELETE" });
        await loadKnowledge();
        if (document.querySelector("#report-content").hidden === false) renderReport(lastReport);
      });
      footer.append(remove); card.append(title, notes, footer); return card;
    }));
    knowledgeEmpty.hidden = knowledgeEntries.length > 0;
    knowledgeState.textContent = `${knowledgeEntries.length} reference${knowledgeEntries.length === 1 ? "" : "s"}`;
  };
  const loadKnowledge = async () => {
    try {
      const response = await fetch(`${config.apiBase}/knowledge-base`); const payload = await response.json();
      if (!response.ok) throw new Error(payload.errors?.[0] || "Knowledge base could not be loaded.");
      knowledgeEntries = payload.entries; renderKnowledge();
    } catch (error) { knowledgeState.textContent = error.message; knowledgeEmpty.hidden = false; }
  };
  let lastReport = null;
  document.querySelector("#knowledge-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const response = await fetch(`${config.apiBase}/knowledge-base`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.fromEntries(form)) });
    const payload = await response.json();
    if (!response.ok) { knowledgeState.textContent = payload.errors?.[0] || "Reference could not be added."; return; }
    event.currentTarget.reset(); await loadKnowledge(); if (lastReport) renderReport(lastReport);
  });
  const addChatMessage = (role, text) => {
    const message = document.createElement("div"); message.className = `chat-message ${role}`;
    const label = document.createElement("strong"); label.textContent = role === "user" ? "You" : "Evidence desk";
    const body = document.createElement("p"); body.textContent = text;
    message.append(label, body); chatMessages.append(message); chatMessages.scrollTop = chatMessages.scrollHeight;
  };
  document.querySelector("#chat-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = chatInput.value.trim();
    if (!message) return;
    addChatMessage("user", message); chatInput.value = ""; chatSubmit.disabled = true; chatState.textContent = "Thinking with your sources...";
    try {
      const response = await fetch(`${config.apiBase}/chat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, articleText: input.value.trim() }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.errors?.[0] || "The evidence desk could not answer.");
      addChatMessage("assistant", payload.answer); chatState.textContent = "Answers use your reference shelf";
    } catch (error) { addChatMessage("assistant", error.message); chatState.textContent = "Try again when the model is available"; }
    finally { chatSubmit.disabled = false; chatInput.focus(); }
  });
  document.querySelector("#analyze-button").addEventListener("click", async () => {
    if (!input.value.trim()) { input.focus(); reportState.textContent = "Add an article first"; return; }
    const isUrl = /^https?:\/\//i.test(input.value.trim());
    const button = document.querySelector("#analyze-button");
    button.disabled = true;
    reportState.textContent = isUrl ? "Fetching article and asking the course model..." : "Analyzing locally...";
    try {
      let report;
      let articleText = input.value.trim();
      if (isUrl) {
        const response = await fetch(`${config.apiBase}/analyze`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: input.value.trim() }) });
        const payload = await response.json();
         if (!response.ok) throw new Error(payload.errors?.[0] || "The article could not be analyzed.");
         report = payload.report;
         articleText = payload.articleText;
      } else {
        report = analyze(input.value);
      }
       lastReport = report;
       renderReport(report);
      reportState.textContent = isUrl ? "Course model analysis complete" : "Analysis complete";
      try {
        const historyResponse = await fetch(`${config.apiBase}/history`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ inputType: isUrl ? "url" : "text", sourceUrl: isUrl ? input.value.trim() : "", articleText, report }) });
        if (!historyResponse.ok) throw new Error("History could not be saved.");
        await loadHistory();
      } catch (historyError) {
        historyState.textContent = historyError.message;
      }
    } catch (error) {
      reportState.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
  loadHistory();
  loadKnowledge();
  runtime.markReady();
}


try {
  bootstrap();
} catch (error) {
  window.GizmoAppRuntime?.showFatalError(error);
}
