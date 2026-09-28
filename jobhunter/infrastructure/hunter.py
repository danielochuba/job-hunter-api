"""Hunter.io adapter for the EmailFinder port (optional: disabled without HUNTER_API_KEY)."""
import requests


class HunterFinder:
    def __init__(self, api_key=None, timeout=20):
        self.api_key = api_key
        self.timeout = timeout

    @property
    def enabled(self):
        return bool(self.api_key)

    def search(self, domain, company):
        if not self.enabled or not (domain or company):
            return []
        params = {"api_key": self.api_key, "limit": 10}
        params.update({"domain": domain} if domain else {"company": company})
        try:
            r = requests.get("https://api.hunter.io/v2/domain-search", params=params, timeout=self.timeout)
        except requests.RequestException:
            return []
        if r.status_code != 200:
            return []
        return [{"email": e["value"], "name": " ".join(x for x in (e.get("first_name"), e.get("last_name")) if x) or None,
                 "role": e.get("position") or e.get("department"), "confidence": e.get("confidence")}
                for e in (r.json().get("data") or {}).get("emails", [])]


class DesktopNotifier:
    """OS toast via plyer (the API runs locally). Silently no-ops where unsupported."""

    def desktop(self, title, body):
        try:
            from plyer import notification
            notification.notify(title=title[:63], message=(body or " ")[:250], app_name="JobHunter", timeout=8)
        except Exception:  # noqa: BLE001
            pass
