"""Local Flask interface for a personal Ollama-powered study assistant."""

import hashlib
import json
import math
import os
import sqlite3
from contextlib import closing
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Flask, abort, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["OLLAMA_URL"] = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
app.config["OLLAMA_EMBED_URL"] = os.environ.get("OLLAMA_EMBED_URL", "http://localhost:11434/api/embed")
app.config["OLLAMA_MODEL"] = "qwen3:1.7b"
app.config["OLLAMA_EMBED_MODEL"] = "nomic-embed-text"
app.config["OLLAMA_TIMEOUT"] = 60
app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "uploads")
app.config["DOCUMENT_INDEX_PATH"] = os.path.join(app.root_path, "study-library.sqlite3")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
app.config["CHUNK_SIZE"] = 900
app.config["CHUNK_OVERLAP"] = 150
app.config["RETRIEVAL_LIMIT"] = 4
app.config["RETRIEVAL_MIN_SCORE"] = 0.30

ALLOWED_UPLOAD_EXTENSIONS = {"pdf", "txt", "md", "docx"}
SYSTEM_MESSAGE = {"role": "system", "content": (
    "You are a helpful personal assistant for a Generative AI Literacy and "
    "Applications lab. Give accurate, clear, and practical answers."
)}


class DocumentIndexError(Exception):
    """Raised when a local document cannot be extracted or embedded."""


def is_allowed_upload(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_UPLOAD_EXTENSIONS


def upload_directory():
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    return app.config["UPLOAD_FOLDER"]


def document_list():
    documents = []
    for filename in os.listdir(upload_directory()):
        path = os.path.join(upload_directory(), filename)
        if os.path.isfile(path) and is_allowed_upload(filename):
            documents.append({"name": filename, "size": os.path.getsize(path)})
    return sorted(documents, key=lambda document: document["name"].lower())


def document_path(filename):
    """Return a validated local Study Library file path, or abort with 404."""
    safe_filename = secure_filename(filename)
    if not safe_filename or safe_filename != filename or not is_allowed_upload(filename):
        abort(404)
    path = os.path.join(upload_directory(), safe_filename)
    if not os.path.isfile(path):
        abort(404)
    return path


def index_connection():
    """Open the small local SQLite index and ensure its schema exists."""
    connection = sqlite3.connect(app.config["DOCUMENT_INDEX_PATH"])
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
          filename TEXT PRIMARY KEY, content_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
          id INTEGER PRIMARY KEY,
          filename TEXT NOT NULL REFERENCES documents(filename) ON DELETE CASCADE,
          chunk_number INTEGER NOT NULL, content TEXT NOT NULL, embedding TEXT NOT NULL,
          UNIQUE(filename, chunk_number)
        );
    """)
    return connection


def extract_document_text(path):
    """Extract text locally from a supported file or raise a clear error."""
    extension = os.path.splitext(path)[1].lower()
    if extension in {".txt", ".md"}:
        with open(path, "r", encoding="utf-8", errors="replace") as document:
            return document.read()
    if extension == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise DocumentIndexError("PDF indexing needs pypdf. Run pip install -r requirements.txt and try Refresh.") from error
        try:
            return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        except Exception as error:
            raise DocumentIndexError(f"Could not read this PDF: {error}") from error
    if extension == ".docx":
        try:
            from docx import Document
        except ImportError as error:
            raise DocumentIndexError("DOCX indexing needs python-docx. Run pip install -r requirements.txt and try Refresh.") from error
        try:
            return "\n".join(paragraph.text for paragraph in Document(path).paragraphs)
        except Exception as error:
            raise DocumentIndexError(f"Could not read this DOCX file: {error}") from error
    raise DocumentIndexError("This file type is not supported.")


def split_text(text):
    """Split text into overlapping, readable chunks for local retrieval."""
    text = " ".join(text.split())
    if not text:
        return []
    size, overlap, chunks, start = app.config["CHUNK_SIZE"], min(app.config["CHUNK_OVERLAP"], app.config["CHUNK_SIZE"] - 1), [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = text.rfind(" ", start, end)
            if boundary > start + size // 2:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def ollama_embeddings(texts):
    """Request embeddings only from the local Ollama API."""
    payload = json.dumps({"model": app.config["OLLAMA_EMBED_MODEL"], "input": texts}).encode("utf-8")
    embedding_request = Request(app.config["OLLAMA_EMBED_URL"], data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(embedding_request, timeout=app.config["OLLAMA_TIMEOUT"]) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise DocumentIndexError(f"Ollama embedding returned HTTP {error.code}. Pull nomic-embed-text and try again.") from error
    except (URLError, TimeoutError, OSError) as error:
        raise DocumentIndexError("Could not reach Ollama for local document search. Start Ollama and try again.") from error
    except json.JSONDecodeError as error:
        raise DocumentIndexError("Ollama returned unreadable embedding data.") from error
    embeddings = response_data.get("embeddings") if isinstance(response_data, dict) else None
    if not isinstance(embeddings, list) or len(embeddings) != len(texts) or any(not isinstance(vector, list) or not vector for vector in embeddings):
        raise DocumentIndexError("Ollama returned unexpected embedding data.")
    try:
        return [[float(value) for value in vector] for vector in embeddings]
    except (TypeError, ValueError) as error:
        raise DocumentIndexError("Ollama returned invalid embedding values.") from error


def index_document(filename):
    """Extract and replace one document's chunks, skipping unchanged files."""
    path = os.path.join(upload_directory(), filename)
    with open(path, "rb") as document:
        content_hash = hashlib.sha256(document.read()).hexdigest()
    with closing(index_connection()) as connection:
        saved = connection.execute("SELECT content_hash FROM documents WHERE filename = ?", (filename,)).fetchone()
        if saved and saved["content_hash"] == content_hash:
            return False
    chunks = split_text(extract_document_text(path))
    if not chunks:
        raise DocumentIndexError("No readable text was found in this document.")
    embeddings = ollama_embeddings(chunks)
    with closing(index_connection()) as connection:
        connection.execute("DELETE FROM documents WHERE filename = ?", (filename,))
        connection.execute("INSERT INTO documents (filename, content_hash) VALUES (?, ?)", (filename, content_hash))
        connection.executemany(
            "INSERT INTO chunks (filename, chunk_number, content, embedding) VALUES (?, ?, ?, ?)",
            [(filename, number, chunk, json.dumps(embedding)) for number, (chunk, embedding) in enumerate(zip(chunks, embeddings))],
        )
        connection.commit()
    return True


def refresh_document_index():
    """Index new/changed files and remove records whose local files are gone."""
    filenames = {document["name"] for document in document_list()}
    with closing(index_connection()) as connection:
        stale = connection.execute("SELECT filename FROM documents").fetchall()
        connection.executemany("DELETE FROM documents WHERE filename = ?", [(row["filename"],) for row in stale if row["filename"] not in filenames])
        connection.commit()
    errors = []
    for filename in sorted(filenames):
        try:
            index_document(filename)
        except DocumentIndexError as error:
            errors.append(f"{filename}: {error}")
    return errors


def cosine_similarity(left, right):
    if len(left) != len(right):
        return 0.0
    magnitude = math.sqrt(sum(value * value for value in left)) * math.sqrt(sum(value * value for value in right))
    return sum(a * b for a, b in zip(left, right)) / magnitude if magnitude else 0.0


def retrieve_relevant_chunks(question):
    """Find relevant chunks in the local SQLite index."""
    with closing(index_connection()) as connection:
        rows = connection.execute("SELECT filename, content, embedding FROM chunks").fetchall()
    if not rows:
        return []
    question_embedding = ollama_embeddings([question])[0]
    matches = []
    for row in rows:
        try:
            score = cosine_similarity(question_embedding, json.loads(row["embedding"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if score >= app.config["RETRIEVAL_MIN_SCORE"]:
            matches.append({"filename": row["filename"], "content": row["content"], "score": score})
    return sorted(matches, key=lambda match: match["score"], reverse=True)[:app.config["RETRIEVAL_LIMIT"]]


def retrieval_system_message(matches):
    context = "\n\n".join(f"Document: {match['filename']}\nPassage: {match['content']}" for match in matches)
    return {"role": "system", "content": (
        "Use these passages from the user's local Study Library when answering. Base document claims only on these passages and say when they do not answer the question. Do not invent, guess, or cite filenames; the interface adds source labels only from the retrieved documents.\n\n" + context
    )}


@app.get("/")
def index():
    return render_template("index.html", model=app.config["OLLAMA_MODEL"])


@app.get("/api/documents")
def list_documents():
    return jsonify(documents=document_list(), index_errors=refresh_document_index())


@app.get("/api/documents/<filename>/content")
def view_document(filename):
    """Serve the original document inline, allowing browsers to render PDFs."""
    document_path(filename)
    return send_from_directory(upload_directory(), filename, as_attachment=False)


@app.get("/api/documents/<filename>/preview")
def preview_document(filename):
    """Return readable text for non-PDF Study Library document previews."""
    path = document_path(filename)
    if os.path.splitext(filename)[1].lower() == ".pdf":
        return jsonify(error="PDF files open directly in a new browser tab."), 400
    try:
        text = extract_document_text(path)
    except DocumentIndexError as error:
        return jsonify(error=str(error)), 422
    return jsonify(name=filename, content=text)


@app.post("/api/documents")
def upload_document():
    document = request.files.get("document")
    if document is None or not document.filename:
        return jsonify(error="Choose a document to upload."), 400
    filename = secure_filename(document.filename)
    if not filename or not is_allowed_upload(filename):
        return jsonify(error="Upload a PDF, TXT, Markdown, or DOCX file."), 400
    path = os.path.join(upload_directory(), filename)
    if os.path.exists(path):
        return jsonify(error="A document with that name already exists."), 409
    document.save(path)
    try:
        index_document(filename)
    except DocumentIndexError as error:
        return jsonify(message=f"Uploaded {filename}, but it was not indexed.", warning=str(error), documents=document_list()), 201
    return jsonify(message=f"Uploaded and indexed {filename}.", documents=document_list()), 201


@app.delete("/api/documents/<filename>")
def delete_document(filename):
    safe_filename = secure_filename(filename)
    if not safe_filename or safe_filename != filename or not is_allowed_upload(filename):
        return jsonify(error="That document name is not valid."), 400
    path = os.path.join(upload_directory(), safe_filename)
    if not os.path.isfile(path):
        return jsonify(error="Document not found."), 404
    os.remove(path)
    with closing(index_connection()) as connection:
        connection.execute("DELETE FROM documents WHERE filename = ?", (safe_filename,))
        connection.commit()
    return jsonify(message=f"Deleted {safe_filename} and its search index.", documents=document_list())


@app.errorhandler(413)
def upload_too_large(_error):
    return jsonify(error="Files must be 10 MB or smaller."), 413


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
        return jsonify(error="Send a JSON object with a messages list."), 400
    messages = payload["messages"]
    if not messages:
        return jsonify(error="Enter a message before sending."), 400
    if len(messages) > 100:
        return jsonify(error="Conversation is too long. Start a new chat."), 400
    clean_messages = []
    for message in messages:
        if not isinstance(message, dict):
            return jsonify(error="Each message must be an object."), 400
        role, content = message.get("role"), message.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            return jsonify(error="Messages need a user or assistant role and text content."), 400
        content = content.strip()
        if not content:
            return jsonify(error="Messages cannot be empty."), 400
        if len(content) > 12000:
            return jsonify(error="A message is too long (maximum 12,000 characters)."), 400
        clean_messages.append({"role": role, "content": content})
    matches, retrieval_notice = [], ""
    try:
        matches = retrieve_relevant_chunks(clean_messages[-1]["content"])
        if not matches:
            retrieval_notice = "No relevant document passages were found in your Study Library."
    except DocumentIndexError as error:
        retrieval_notice = f"Study Library search was unavailable: {error}"
    system_messages = [SYSTEM_MESSAGE]
    if matches:
        system_messages.append(retrieval_system_message(matches))
    ollama_payload = json.dumps({"model": app.config["OLLAMA_MODEL"], "messages": [*system_messages, *clean_messages], "stream": False}).encode("utf-8")
    ollama_request = Request(app.config["OLLAMA_URL"], data=ollama_payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(ollama_request, timeout=app.config["OLLAMA_TIMEOUT"]) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return jsonify(error=f"Ollama returned HTTP {error.code}. Check that the model is available."), 502
    except (URLError, TimeoutError, OSError):
        return jsonify(error="Could not reach Ollama. Start Ollama and try again."), 503
    except json.JSONDecodeError:
        return jsonify(error="Ollama returned an unreadable response."), 502
    if not isinstance(response_data, dict):
        return jsonify(error="Ollama returned an unexpected response."), 502
    reply = response_data.get("message", {}).get("content")
    if not isinstance(reply, str) or not reply.strip():
        return jsonify(error="Ollama returned no assistant message."), 502
    # Attribution comes exclusively from chunks retrieved for this answer.
    sources = list(dict.fromkeys(match["filename"] for match in matches))
    return jsonify(message={"role": "assistant", "content": reply.strip()}, sources=sources, retrieval_notice=retrieval_notice)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=True)
