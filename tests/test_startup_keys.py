import pytest

from pjm_nowcast.settings import Settings


def test_refuses_svm_private_key(monkeypatch):
    monkeypatch.setenv("SVM_PRIVATE_KEY", "should-never-be-here")
    with pytest.raises(RuntimeError, match="SVM_PRIVATE_KEY"):
        Settings(env="test", x402_disabled=True, run_poller=False)


def test_refuses_evm_private_key(monkeypatch):
    monkeypatch.setenv("EVM_PRIVATE_KEY", "nope")
    with pytest.raises(RuntimeError, match="EVM_PRIVATE_KEY"):
        Settings(env="test", x402_disabled=True, run_poller=False)


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
