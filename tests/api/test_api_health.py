import requests, time

def test_api_health():
    url = "https://localhost/api/status"
    for _ in range(30):
        try:
            r = requests.get(url, verify=False, timeout=5)
            if r.status_code in (200, 302, 401):
                # 200 if open, 401 if auth required; both indicate the endpoint is alive
                assert True
                return
        except Exception:
            pass
        time.sleep(5)
    raise AssertionError("API health endpoint not reachable in time")
