"""Tests for Step 16: multi-template Excel export and PDF export."""
import io

import pytest
from openpyxl import load_workbook


@pytest.fixture
def app():
    from app import app as flask_app
    flask_app.config.update({"TESTING": True, "SECRET_KEY": "test-secret"})
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(client):
    from database.db import get_db
    conn = get_db()
    uid = conn.execute("SELECT id FROM users WHERE email = %s",
                       ("plankmax05@gmail.com",)).fetchone()["id"]
    conn.close()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    return client


@pytest.mark.parametrize("url", ["/expenses/export", "/expenses/export/pdf"])
def test_logged_out_redirects_to_login(client, url):
    resp = client.get(url)
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]


@pytest.mark.parametrize("template", ["minimal", "professional", "analytics", "aesthetic"])
def test_each_template_is_valid_xlsx(auth_client, template):
    resp = auth_client.get(f"/expenses/export?template={template}")
    assert resp.status_code == 200
    assert f"expenses_{template}_" in resp.headers["Content-Disposition"]
    wb = load_workbook(io.BytesIO(resp.data))
    ws = wb["Expenses"]
    assert [c.value for c in ws[1]][:4] == ["Date", "Category", "Description", "Amount"]
    assert (template == "analytics") == ("Summary" in wb.sheetnames)


def test_invalid_template_falls_back_to_minimal(auth_client):
    resp = auth_client.get("/expenses/export?template=../evil")
    assert resp.status_code == 200
    assert "expenses_minimal_" in resp.headers["Content-Disposition"]


def test_pdf_export(auth_client):
    resp = auth_client.get("/expenses/export/pdf")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data.startswith(b"%PDF")
    assert "expenses_statement_" in resp.headers["Content-Disposition"]


def test_pdf_invalid_dates_still_exports(auth_client):
    resp = auth_client.get("/expenses/export/pdf?date_from=2026-05-05&date_to=2026-05-01")
    assert resp.status_code == 200 and resp.data.startswith(b"%PDF")


def test_pdf_builder_empty():
    from database.pdf import build_expense_pdf
    out = build_expense_pdf([], {"total_spent": 0, "transaction_count": 0,
                                 "top_category": "—"}, [], None, None, "A & B")
    assert out.startswith(b"%PDF")


def test_profile_has_export_modal(auth_client):
    html = auth_client.get("/profile").get_data(as_text=True)
    assert 'id="exportModal"' in html and "js/export.js" in html
