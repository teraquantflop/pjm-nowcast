from pathlib import Path

import pytest

from pjm_nowcast.db.store import Store
from pjm_nowcast.settings import Settings


def test_refuses_svm_private_key(monkeypatch):
    monkeypatch.setenv("SVM_PRIVATE_KEY", "should-never-be-here")
    with pytest.raises(RuntimeError, match="SVM_PRIVATE_KEY"):
        Settings(env="test", x402_disabled=True, run_poller=False)


def test_refuses_evm_private_key(monkeypatch):
    monkeypatch.setenv("EVM_PRIVATE_KEY", "nope")
    with pytest.raises(RuntimeError, match="EVM_PRIVATE_KEY"):
        Settings(env="test", x402_disabled=True, run_poller=False)


def test_production_relative_data_dir_uses_volume(monkeypatch, tmp_path):
    monkeypatch.delenv("SVM_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("EVM_PRIVATE_KEY", raising=False)
    s = Settings(
        env="production",
        public_base_url="https://example.com",
        x402_disabled=False,
        pay_to_evm_address="0x1111111111111111111111111111111111111111",
        data_dir="./var",
        run_poller=False,
    )
    assert s.data_dir == Path("/data")
    assert s.database_path == Path("/data/pjm-nowcast.sqlite")
    assert s.snapshot_path == Path("/data/snapshot.json")


def test_development_keeps_relative_var_under_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    s = Settings(env="development", data_dir="./var", run_poller=False, x402_disabled=True)
    assert s.data_dir == tmp_path / "var"
    assert s.database_path == tmp_path / "var" / "pjm-nowcast.sqlite"
    assert s.snapshot_path == tmp_path / "var" / "snapshot.json"
    assert s.database_path != s.data_dir
    assert not s.database_path.is_dir() or not s.database_path.exists()


def test_database_path_directory_is_not_used_as_sqlite_file(tmp_path):
    volume = tmp_path / "data"
    volume.mkdir()
    s = Settings(
        env="test",
        data_dir=volume,
        database_path=volume,
        snapshot_path=volume,
        run_poller=False,
        x402_disabled=True,
    )
    assert s.data_dir == volume
    assert s.database_path == volume / "pjm-nowcast.sqlite"
    assert s.snapshot_path == volume / "snapshot.json"


def test_store_opens_file_under_directory(tmp_path):
    volume = tmp_path / "data"
    volume.mkdir()
    store = Store(volume)
    try:
        assert store.path == volume / "pjm-nowcast.sqlite"
        assert store.path.is_file()
        assert store.count() == 0
    finally:
        store.close()


def test_store_mkdir_parents(tmp_path):
    db = tmp_path / "nested" / "dir" / "pjm-nowcast.sqlite"
    store = Store(db)
    try:
        assert db.is_file()
    finally:
        store.close()


def test_production_requires_pay_to(monkeypatch):
    monkeypatch.delenv("SVM_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("EVM_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("X402_DISABLED", "false")
    with pytest.raises(RuntimeError, match="PAY_TO"):
        Settings(
            env="production",
            public_base_url="https://example.com",
            x402_disabled=False,
            pay_to_address="",
            pay_to_svm_address="",
            pay_to_evm_address="",
        )
