from tests.conftest import seed_observation


def test_mcp_service_info_free(client):
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert r.status_code == 200
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert names == {
        "service_info",
        "demo_sample",
        "nowcast_latest",
        "nowcast_history",
        "nowcast_history_extended",
    }


def test_mcp_demo_and_latest(client, store):
    seed_observation(store)
    info = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "service_info", "arguments": {}},
        },
    )
    assert info.status_code == 200
    assert info.json()["result"]["isError"] is False
    latest = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "nowcast_latest", "arguments": {}},
        },
    )
    assert latest.status_code == 200
    # X402_DISABLED=true in default tests so the tool runs
    assert latest.json()["result"]["isError"] is False
