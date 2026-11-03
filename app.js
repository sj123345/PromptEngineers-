const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const messagesElement = document.querySelector("#messages");
const statusElement = document.querySelector("#status");
const sendButton = document.querySelector("#send-button");
const uploadForm = document.querySelector("#upload-form");
const documentInput = document.querySelector("#document-input");
const selectedFile = document.querySelector("#selected-file");
const documentList = document.querySelector("#document-list");
const documentStatus = document.querySelector("#document-status");
const refreshDocumentsButton = document.querySelector("#refresh-documents");
const conversation = [];

function appendLinkedText(element, content) {
  const urlPattern = /(https?:\/\/[^\s<]+)/g;
  let lastIndex = 0;
  for (const match of content.matchAll(urlPattern)) {
    const url = match[0];
    const start = match.index;
    element.append(document.createTextNode(content.slice(lastIndex, start)));
    const link = document.createElement("a");
    link.href = url;
    link.textContent = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    element.append(link);
    lastIndex = start + url.length;
  }
  element.append(document.createTextNode(content.slice(lastIndex)));
}

function addMessage(role, content, sources = []) {
  const article = document.createElement("article");
  const label = document.createElement("strong");
  const text = document.createElement("p");
  article.className = `message ${role}-message`;
  label.textContent = role === "user" ? "You" : "✦ Little Star";
  appendLinkedText(text, content);
  article.append(label, text);
  if (role === "assistant" && sources.length) {
    const attribution = document.createElement("p");
    const sourceLabel = document.createElement("span");
    attribution.className = "message-sources";
    sourceLabel.textContent = "Study Library sources: ";
    attribution.append(sourceLabel);
    sources.forEach((source, index) => {
      if (index) attribution.append(document.createTextNode(", "));
      const sourceLink = document.createElement("a");
      sourceLink.href = `/api/documents/${encodeURIComponent(source)}/content`;
      sourceLink.textContent = source;
      sourceLink.target = "_blank";
      sourceLink.rel = "noopener noreferrer";
      attribution.append(sourceLink);
    });
    article.append(attribution);
  }
  messagesElement.append(article);
  article.scrollIntoView({ behavior: "smooth", block: "end" });
}

function setStatus(message = "", isError = false) {
  statusElement.textContent = message;
  statusElement.classList.toggle("error", isError);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = input.value.trim();
  if (!content) {
    setStatus("Please enter a message.", true);
    input.focus();
    return;
  }

  conversation.push({ role: "user", content });
  addMessage("user", content);
  input.value = "";
  input.disabled = true;
  sendButton.disabled = true;
  setStatus("Assistant is thinking…");

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: conversation }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "The request failed.");

    conversation.push(data.message);
    addMessage("assistant", data.message.content, data.sources || []);
    if (data.sources?.length) {
      setStatus(`Answer informed by: ${data.sources.join(", ")}`);
    } else {
      setStatus(data.retrieval_notice || "");
    }
  } catch (error) {
    conversation.pop();
    setStatus(error.message || "A connection error occurred.", true);
  } finally {
    input.disabled = false;
    sendButton.disabled = false;
    input.focus();
  }
});

function setDocumentStatus(message = "", isError = false) {
  documentStatus.textContent = message;
  documentStatus.classList.toggle("error", isError);
}

function formatFileSize(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function renderDocuments(documents) {
  documentList.replaceChildren();
  if (!documents.length) {
    const empty = document.createElement("li");
    empty.className = "empty-library";
    empty.textContent = "Your local study library is ready for its first file.";
    documentList.append(empty);
    return;
  }
  for (const file of documents) {
    const item = document.createElement("li");
    const details = document.createElement("div");
    const name = document.createElement(file.name.toLowerCase().endsWith(".pdf") ? "a" : "button");
    const size = document.createElement("span");
    const remove = document.createElement("button");
    name.className = "document-name";
    name.textContent = file.name;
    if (file.name.toLowerCase().endsWith(".pdf")) {
      name.href = `/api/documents/${encodeURIComponent(file.name)}/content`;
      name.target = "_blank";
      name.rel = "noopener noreferrer";
      name.title = `Open ${file.name} in a new tab`;
    } else {
      name.type = "button";
      name.title = `Preview ${file.name}`;
      name.addEventListener("click", () => previewDocument(file.name));
    }
    size.textContent = formatFileSize(file.size);
    details.append(name, size);
    remove.type = "button";
    remove.className = "delete-button";
    remove.textContent = "Delete";
    remove.addEventListener("click", () => deleteDocument(file.name));
    item.append(details, remove);
    documentList.append(item);
  }
}

async function previewDocument(filename) {
  setDocumentStatus(`Opening preview for ${filename}…`);
  try {
    const data = await responseData(await fetch(`/api/documents/${encodeURIComponent(filename)}/preview`));
    showDocumentPreview(data.name, data.content);
    setDocumentStatus("");
  } catch (error) {
    setDocumentStatus(error.message || "Could not preview the document.", true);
  }
}

function showDocumentPreview(filename, content) {
  const dialog = document.querySelector("#document-preview");
  document.querySelector("#preview-title").textContent = filename;
  document.querySelector("#preview-content").textContent = content || "This document contains no readable text.";
  if (!dialog.open) dialog.showModal();
}

async function responseData(response) {
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The request failed.");
  return data;
}

async function loadDocuments() {
  refreshDocumentsButton.disabled = true;
  try {
    const data = await responseData(await fetch("/api/documents"));
    renderDocuments(data.documents);
    setDocumentStatus(data.index_errors?.join(" ") || "", Boolean(data.index_errors?.length));
  } catch (error) {
    setDocumentStatus(error.message || "Could not refresh the study library.", true);
  } finally {
    refreshDocumentsButton.disabled = false;
  }
}

async function deleteDocument(filename) {
  try {
    const data = await responseData(await fetch(`/api/documents/${encodeURIComponent(filename)}`, { method: "DELETE" }));
    renderDocuments(data.documents);
    setDocumentStatus(data.warning || data.message, Boolean(data.warning));
  } catch (error) {
    setDocumentStatus(error.message || "Could not delete the document.", true);
  }
}

documentInput.addEventListener("change", () => {
  selectedFile.textContent = documentInput.files[0]?.name || "No file selected";
});

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!documentInput.files[0]) {
    setDocumentStatus("Choose a document to upload.", true);
    return;
  }
  const submit = uploadForm.querySelector("button[type='submit']");
  submit.disabled = true;
  setDocumentStatus("Uploading to your local study library…");
  try {
    const formData = new FormData(uploadForm);
    const data = await responseData(await fetch("/api/documents", { method: "POST", body: formData }));
    renderDocuments(data.documents);
    uploadForm.reset();
    selectedFile.textContent = "No file selected";
    setDocumentStatus(data.message);
  } catch (error) {
    setDocumentStatus(error.message || "Could not upload the document.", true);
  } finally {
    submit.disabled = false;
  }
});

refreshDocumentsButton.addEventListener("click", loadDocuments);
document.querySelector("#close-preview").addEventListener("click", () => document.querySelector("#document-preview").close());
loadDocuments();
