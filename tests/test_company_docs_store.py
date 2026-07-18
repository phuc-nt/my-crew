"""v7 M19 S1: Company Docs flat-file store + the bounded internal-only render. Offline.

Load-bearing:
- CRUD round-trips through frontmatter (title/updated preserved).
- An over-size doc is REJECTED at write (never stored truncated).
- render_company_docs is bounded by MAX_INJECT_CHARS and DECLARES truncation.
- The pool loader drops a stale/typo slug instead of crashing.
"""

from __future__ import annotations

import pytest

from my_crew.company_docs import inject, store
from my_crew.company_docs.pool import load_company_docs


@pytest.fixture
def docs_dir(tmp_path, monkeypatch):
    """Point the store at a throwaway dir so tests never touch the repo's company-docs/."""
    d = tmp_path / "company-docs"
    monkeypatch.setattr("my_crew.company_docs.store._DOCS_DIR", d)
    return d


# --- slug ---


def test_slugify():
    # Vietnamese diacritics fold to ascii → a meaningful slug, not a collapse to "doc".
    assert store.slugify("Quy trình Nghỉ Phép") == "quy-trinh-nghi-phep"
    assert store.slugify("Đơn xin nghỉ") == "don-xin-nghi"  # đ → d
    assert store.slugify("Leave Policy 2026!") == "leave-policy-2026"
    assert store.slugify("日本語") == "doc"  # no latin content → fallback
    assert store.slugify("") == "doc"


def test_slugify_distinct_vietnamese_titles_dont_collide():
    # the bug the diacritic fold fixes: two different VN titles must give different slugs
    assert store.slugify("Chính sách") != store.slugify("Quy trình")


def test_invalid_slug_rejected(docs_dir):
    with pytest.raises(store.InvalidSlugError):
        store.get_doc("../etc/passwd")
    with pytest.raises(store.InvalidSlugError):
        store.get_doc("Bad Slug")


# --- CRUD ---


def test_save_get_list_delete_roundtrip(docs_dir):
    assert store.list_docs() == []
    saved = store.save_doc("leave-policy", title="Nghỉ phép", body="12 ngày/năm",
                           updated="2026-07-04")
    assert saved.slug == "leave-policy"
    got = store.get_doc("leave-policy")
    assert got is not None
    assert got.title == "Nghỉ phép" and got.updated == "2026-07-04"
    assert got.body == "12 ngày/năm"
    assert [d.slug for d in store.list_docs()] == ["leave-policy"]
    assert store.delete_doc("leave-policy") is True
    assert store.get_doc("leave-policy") is None
    assert store.delete_doc("leave-policy") is False  # already gone


def test_save_rejects_oversize(docs_dir):
    with pytest.raises(store.DocTooLargeError):
        store.save_doc("big", title="x", body="a" * (store.MAX_DOC_CHARS + 1), updated="")


def test_get_missing_returns_none(docs_dir):
    assert store.get_doc("nope") is None


# --- pool loader ---


def test_pool_empty_no_disk_read():
    assert load_company_docs(()) == ()


def test_pool_drops_missing_and_invalid(docs_dir):
    store.save_doc("real", title="R", body="b", updated="")
    pool = load_company_docs(("real", "ghost", "Bad Slug"))
    assert [d.slug for d in pool] == ["real"]  # ghost + invalid dropped, no crash


def test_pool_preserves_declared_order(docs_dir):
    store.save_doc("a", title="A", body="1", updated="")
    store.save_doc("b", title="B", body="2", updated="")
    assert [d.slug for d in load_company_docs(("b", "a"))] == ["b", "a"]


# --- bounded render ---


def _doc(slug, body):
    return store.CompanyDoc(slug=slug, title=slug.title(), updated="", body=body)


def test_render_empty_is_blank():
    assert inject.render_company_docs([]) == ""


def test_render_wraps_in_block():
    out = inject.render_company_docs([_doc("leave", "12 ngày")])
    assert out.startswith("<company_docs>") and out.endswith("</company_docs>")
    assert "## Leave" in out and "12 ngày" in out


def test_render_bounded_declares_truncation(monkeypatch):
    monkeypatch.setattr(inject, "MAX_INJECT_CHARS", 30)
    docs = [_doc("a", "x" * 25), _doc("b", "y" * 25)]
    out = inject.render_company_docs(docs)
    # first doc fits, second would overflow → dropped with a declared marker
    assert "xxxx" in out and "yyyy" not in out
    assert "lược bớt" in out


def test_render_first_doc_always_included_even_if_over_budget(monkeypatch):
    monkeypatch.setattr(inject, "MAX_INJECT_CHARS", 5)
    out = inject.render_company_docs([_doc("a", "z" * 100)])
    assert "zzzz" in out  # never emit an empty block when a doc exists
