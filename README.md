# AI Literacy Lab Assistant

A small personal chat app for the Generative AI Literacy and Applications lab.
It runs only on your Mac and sends each conversation, including prior turns, to
the local Ollama model `qwen3:1.7b`. The Study Library reads supported files on
your Mac, stores chunk embeddings and metadata in the local SQLite file
`study-library.sqlite3`, and supplies relevant passages to the local chat model.
It does not use a login system, cloud service, web search, or streaming responses.

## Requirements

- macOS with Python 3.9 or newer
- [Ollama](https://ollama.com/) installed and running locally
- The `qwen3:1.7b` and `nomic-embed-text` models downloaded

## Setup and run

From this project directory, create and activate a virtual environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

In another Terminal window, ensure Ollama is available and download the model
once if needed:

```sh
ollama serve
ollama pull qwen3:1.7b
ollama pull nomic-embed-text
```

Start the web app:

```sh
python app.py
```

Open <http://127.0.0.1:5050> in a browser. Flask is explicitly bound to
`127.0.0.1`, so it is not exposed to your local network. Stop the server with
`Control-C`.

## Test

Run the automated route tests without contacting Ollama:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

For a manual test, confirm `ollama serve` is running, open the app, ask a
question, then send a follow-up that relies on the first response. To verify
error handling, stop Ollama and submit another message; the interface should
show a connection error and remain usable.

## Local Study Library

Use the Study Library under the chat to upload, refresh, and delete local PDF,
TXT, Markdown, and DOCX files. An upload is extracted, split into overlapping
passages, and embedded by the local Ollama `nomic-embed-text` model. Ask a
question normally; the assistant retrieves relevant passages, provides them to
the `qwen3:1.7b` chat model, and displays the actual filename(s) of the
retrieved document(s) directly below that answer. It never invents sources.
PDF filenames open the original local PDF in a new browser tab, where the
browser's normal scroll and zoom controls are available. TXT, Markdown, and
DOCX filenames open a readable in-app preview. If there are no relevant
passages, or extraction/embedding fails, the interface says so rather than
treating a document as read.

Filenames are sanitized, duplicate filenames are not overwritten, and each
upload is limited to 10 MB. Files remain in `uploads/`; their SQLite search
index remains on this Mac and is removed when a document is deleted. Refresh
indexes new or changed files without creating duplicate chunks.

## Project layout

- `app.py` — Flask routes and local Ollama request handling
- `templates/` and `static/` — responsive browser interface
- `uploads/` — local study documents (created on first use; do not commit)
- `study-library.sqlite3` — local Study Library retrieval index (created on first use; do not commit)
- `tests/` — API validation tests
