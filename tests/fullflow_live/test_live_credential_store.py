"""Nhóm G — kho credential mã hoá (P4), dữ liệu thật, đĩa thật.

Không gọi model: cái cần chứng minh ở đây là dữ liệu và đĩa, không phải hành vi của
model. Vẫn nằm trong package live vì nó thuộc cùng một lời hứa — "mọi kết nối và data
phải thật": Fernet thật, file thật, quyền file thật, và một lượt `grep` thật trên cây
thư mục để chứng minh token không nằm plaintext ở đâu cả.

CẢNH BÁO đường dẫn: `credential_store` bind `DATA_DIR` NGAY LÚC IMPORT, nên bản vá
`settings.DATA_DIR` của harness KHÔNG với tới nó. Mọi case ở đây phải tự vá
`credential_store.DATA_DIR`; nếu không, test sẽ ghi vào `.data/accounts/` THẬT của
người dùng. Đó là lý do fixture `_isolated_store` tồn tại và mọi case đều phải dùng nó.
"""

from __future__ import annotations

import pytest

from my_crew.config import credential_store as cred_mod
from my_crew.config.credential_resolver import resolve_service_credentials
from my_crew.config.credential_store import CredentialDecryptError, CredentialStore

#: Token giả nhưng có hình dạng thật, và là một chuỗi duy nhất để lượt grep cuối
#: không thể khớp nhầm với thứ khác trong cây thư mục.
FAKE_TOKEN = "EAAG-fullflow-live-sentinel-9f3a1c7e-do-not-use"


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Kho ghi vào tmp, với master key riêng của case.

    Hai lớp cách ly, cả hai đều bắt buộc:
      - `credential_store.DATA_DIR` → tmp (bind lúc import, harness không vá tới).
      - `MY_CREW_CRED_KEY` đặt sẵn → `_load_or_create_master_key` không đi vào nhánh
        sinh key mới, nên không có lượt ghi nào chạm `.env` thật.
    """
    from cryptography.fernet import Fernet

    data_dir = tmp_path / "creddata"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cred_mod, "DATA_DIR", data_dir)
    monkeypatch.setenv(cred_mod.MASTER_KEY_ENV, Fernet.generate_key().decode("ascii"))
    return data_dir


def _all_bytes_under(root) -> bytes:
    return b"\n".join(p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file())


# --- G1: vòng tròn put → get → resolve ----------------------------------------------


def test_g1_a_stored_token_round_trips_and_never_lands_in_plaintext(isolated_store):
    """Ghi vào, đọc ra đúng giá trị — và không byte nào trên đĩa chứa token thô.

    Lượt grep cuối chính là lời hứa mà module này bán: một bản backup `.data/` hay một
    lượt `grep -r` trên repo không bao giờ lòi ra token. Đo trên toàn bộ cây thư mục
    chứ không chỉ file credentials.enc, vì rò rỉ thường nằm ở chỗ khác (file tạm, bản
    sao lưu, log)."""
    store = CredentialStore()
    store.put("meta-ads-main", {"token": FAKE_TOKEN, "account": "act_123"})

    assert store.get("meta-ads-main") == {"token": FAKE_TOKEN, "account": "act_123"}

    on_disk = _all_bytes_under(isolated_store)
    assert on_disk, "phải có file nào đó được ghi ra"
    assert FAKE_TOKEN.encode() not in on_disk, (
        "token nằm plaintext trên đĩa — đây đúng là thứ kho mã hoá tồn tại để chặn"
    )

    resolved = resolve_service_credentials({"account": "meta-ads-main"}, store=store)
    assert resolved == {"token": FAKE_TOKEN, "account": "act_123"}


def test_g2_the_file_is_owner_only(isolated_store):
    """Quyền 0600: mã hoá mà để file world-readable thì chỉ còn là nửa lời hứa."""
    CredentialStore().put("zalo-oa-main", {"token": FAKE_TOKEN})
    cred_path = isolated_store / "accounts" / "zalo-oa-main" / "credentials.enc"
    assert cred_path.exists(), cred_path
    assert oct(cred_path.stat().st_mode)[-3:] == "600", oct(cred_path.stat().st_mode)


# --- G3/G4: hai đường hỏng phải KÊU chứ không im -------------------------------------


def test_g3_a_missing_credential_raises_instead_of_returning_empty(isolated_store):
    """Không có credential phải nổ, không được trả dict rỗng.

    Trả rỗng sẽ bị đọc thành "chưa cấu hình" và gửi request đi mà không có auth — hỏng
    tệ hơn là crash, vì nó im lặng."""
    with pytest.raises(CredentialDecryptError):
        CredentialStore().get("khong-ton-tai")


def test_g4_a_wrong_master_key_raises_and_never_leaks_the_value(isolated_store, monkeypatch):
    """Xoay key mà quên dữ liệu cũ → nổ rõ ràng, và thông báo lỗi không chứa gì bí mật."""
    from cryptography.fernet import Fernet

    CredentialStore().put("meta-ads-main", {"token": FAKE_TOKEN})
    monkeypatch.setenv(cred_mod.MASTER_KEY_ENV, Fernet.generate_key().decode("ascii"))

    with pytest.raises(CredentialDecryptError) as excinfo:
        CredentialStore().get("meta-ads-main")
    assert FAKE_TOKEN not in str(excinfo.value), (
        "thông báo lỗi của kho credential không bao giờ được chứa giá trị"
    )


def test_g5_a_broken_account_reference_never_falls_back_to_the_env_token(
    isolated_store, monkeypatch
):
    """Ưu tiên phân giải: `account` gõ sai phải nổ, KHÔNG được rơi về `token_env`.

    Rơi về sẽ khiến một cấu hình gõ nhầm lặng lẽ gửi request bằng token cũ của tài
    khoản khác — sai người nhận, không ai biết."""
    monkeypatch.setenv("FULLFLOW_FALLBACK_TOKEN", "khong-duoc-dung-toi")
    with pytest.raises(CredentialDecryptError):
        resolve_service_credentials(
            {"account": "khong-ton-tai", "token_env": "FULLFLOW_FALLBACK_TOKEN"},
            store=CredentialStore(),
        )
