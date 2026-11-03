import io
import json
import tempfile
import unittest
from unittest.mock import patch

from app import (
    app,
    extract_document_text,
    index_connection,
    index_document,
    refresh_document_index,
    retrieve_relevant_chunks,
)


class ChatApiTests(unittest.TestCase):
    def setUp(self):
        self.upload_directory = tempfile.TemporaryDirectory()
        self.index_directory = tempfile.TemporaryDirectory()
        app.config.update(
            TESTING=True,
            UPLOAD_FOLDER=self.upload_directory.name,
            DOCUMENT_INDEX_PATH=f"{self.index_directory.name}/library.sqlite3",
        )
        self.client = app.test_client()

    def tearDown(self):
        self.upload_directory.cleanup()
        self.index_directory.cleanup()

    def test_empty_messages_are_rejected(self):
        response = self.client.post("/api/chat", json={"messages": []})
        self.assertEqual(response.status_code, 400)

    def test_uses_required_local_models(self):
        self.assertEqual(app.config["OLLAMA_MODEL"], "qwen3:1.7b")
        self.assertEqual(app.config["OLLAMA_EMBED_MODEL"], "nomic-embed-text")

    @patch("app.urlopen")
    def test_returns_ollama_reply(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            {"message": {"content": "Hello from Ollama"}}
        ).encode()
        response = self.client.post(
            "/api/chat", json={"messages": [{"role": "user", "content": "Hello"}]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["message"]["content"], "Hello from Ollama")

    def test_upload_list_and_delete_document(self):
        response = self.client.post(
            "/api/documents",
            data={"document": (io.BytesIO(b"study notes"), "week one.md")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["documents"][0]["name"], "week_one.md")

        response = self.client.get("/api/documents")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()["documents"]), 1)

        response = self.client.delete("/api/documents/week_one.md")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["documents"], [])

    def test_rejects_unsupported_document(self):
        response = self.client.post(
            "/api/documents",
            data={"document": (io.BytesIO(b"not allowed"), "notes.exe")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)

    def test_rejects_duplicate_document_name(self):
        for _ in range(2):
            response = self.client.post(
                "/api/documents",
                data={"document": (io.BytesIO(b"notes"), "notes.txt")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 409)

    def test_extracts_text_and_splits_it_into_overlapping_index_chunks(self):
        path = f"{self.upload_directory.name}/notes.txt"
        with open(path, "w", encoding="utf-8") as document:
            document.write("Generative AI literacy " * 80)
        self.assertIn("Generative AI literacy", extract_document_text(path))

        with patch("app.ollama_embeddings", side_effect=lambda texts: [[1.0, 0.0] for _ in texts]):
            app.config.update(CHUNK_SIZE=180, CHUNK_OVERLAP=40)
            index_document("notes.txt")
        with index_connection() as connection:
            chunks = connection.execute("SELECT content FROM chunks").fetchall()
        self.assertGreater(len(chunks), 1)
        self.assertIn(chunks[0]["content"][-20:], chunks[1]["content"])

    def test_retrieves_most_relevant_document_chunk(self):
        path = f"{self.upload_directory.name}/retrieval.md"
        with open(path, "w", encoding="utf-8") as document:
            document.write("Embeddings turn text into vectors for similarity search.")
        with patch("app.ollama_embeddings", side_effect=[[[1.0, 0.0]], [[1.0, 0.0]]]):
            index_document("retrieval.md")
            matches = retrieve_relevant_chunks("What are embeddings?")
        self.assertEqual(matches[0]["filename"], "retrieval.md")
        self.assertIn("similarity search", matches[0]["content"])

    @patch("app.urlopen")
    def test_chat_includes_relevant_document_context(self, mock_urlopen):
        path = f"{self.upload_directory.name}/lab.md"
        with open(path, "w", encoding="utf-8") as document:
            document.write("The lab uses retrieval augmented generation for document questions.")
        with patch("app.ollama_embeddings", side_effect=[[[1.0, 0.0]], [[1.0, 0.0]]]):
            index_document("lab.md")
            mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                {"message": {"content": "It uses retrieval augmented generation."}}
            ).encode()
            response = self.client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "How does the lab answer document questions?"}]},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["sources"], ["lab.md"])
        payload = json.loads(mock_urlopen.call_args.args[0].data.decode())
        self.assertIn("retrieval augmented generation", payload["messages"][1]["content"])

    def test_chat_source_attribution_is_limited_to_retrieved_filenames(self):
        with patch("app.retrieve_relevant_chunks", return_value=[
            {"filename": "african-springhare.pdf", "content": "Springhares are nocturnal.", "score": 0.95},
            {"filename": "field-notes.md", "content": "They move by hopping.", "score": 0.91},
            {"filename": "african-springhare.pdf", "content": "They are rodents.", "score": 0.89},
        ]), patch("app.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                {"message": {"content": "The source says they are nocturnal."}}
            ).encode()
            response = self.client.post(
                "/api/chat", json={"messages": [{"role": "user", "content": "Tell me about springhares."}]}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["sources"], ["african-springhare.pdf", "field-notes.md"])

    def test_serves_original_pdf_and_previews_text_document(self):
        with open(f"{self.upload_directory.name}/springhare.pdf", "wb") as document:
            document.write(b"%PDF-1.4\nexample")
        with open(f"{self.upload_directory.name}/springhare-notes.txt", "w", encoding="utf-8") as document:
            document.write("African springhares are nocturnal rodents.")

        pdf_response = self.client.get("/api/documents/springhare.pdf/content")
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response.mimetype, "application/pdf")
        self.assertEqual(pdf_response.data, b"%PDF-1.4\nexample")
        pdf_response.close()

        preview_response = self.client.get("/api/documents/springhare-notes.txt/preview")
        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(preview_response.get_json()["name"], "springhare-notes.txt")
        self.assertIn("nocturnal rodents", preview_response.get_json()["content"])
        self.assertEqual(self.client.get("/api/documents/springhare.pdf/preview").status_code, 400)

    def test_delete_removes_indexed_chunks(self):
        path = f"{self.upload_directory.name}/remove.txt"
        with open(path, "w", encoding="utf-8") as document:
            document.write("This text should be removed from local search.")
        with patch("app.ollama_embeddings", return_value=[[1.0, 0.0]]):
            index_document("remove.txt")
        response = self.client.delete("/api/documents/remove.txt")
        self.assertEqual(response.status_code, 200)
        with index_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0], 0)

    def test_refresh_does_not_duplicate_unchanged_chunks(self):
        with open(f"{self.upload_directory.name}/once.txt", "w", encoding="utf-8") as document:
            document.write("Refresh indexes this document once.")
        with patch("app.ollama_embeddings", return_value=[[1.0, 0.0]]) as embeddings:
            self.assertEqual(refresh_document_index(), [])
            self.assertEqual(refresh_document_index(), [])
        self.assertEqual(embeddings.call_count, 1)
        with index_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
