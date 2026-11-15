"""Polite HTTP helper for TJK program pages."""
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/130 Safari/537.36"
DELAY = 0.5


def get(url, tries=3, timeout=30, extra_headers=None):
    """Polite HTTP GET with retry and 404 fast-exit."""
    headers = {"User-Agent": UA}
    if extra_headers:
        headers.update(extra_headers)
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 404, b""
            time.sleep(2 * (i + 1))
        except Exception:
            if tries == 1:
                break
            time.sleep(2 * (i + 1))
    return None, b""
