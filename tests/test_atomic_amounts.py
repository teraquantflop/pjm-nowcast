from pjm_nowcast.payments.routes import usdc_atomic_amount


def test_usdc_atomic_matches_x402scan_table():
    assert usdc_atomic_amount("$0.02") == "20000"
    assert usdc_atomic_amount("$0.10") == "100000"
    assert usdc_atomic_amount("$0.25") == "250000"
    assert usdc_atomic_amount("0.02") == "20000"
