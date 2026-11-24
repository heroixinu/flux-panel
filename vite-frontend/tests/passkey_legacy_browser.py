#!/usr/bin/env python3
"""A rolling frontend/backend upgrade must not strand the legacy login form."""
import json
from playwright.sync_api import sync_playwright, expect

ORIGIN = "http://localhost:4173"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for code, http_status in [(401, 200), (404, 404)]:
            page = browser.new_page()
            page.route("**/api/v1/passkey/modes", lambda route: route.fulfill(
                status=http_status, content_type="application/json",
                body=json.dumps({"code": code, "msg": "legacy endpoint unavailable", "data": None})))
            page.goto(ORIGIN)
            expect(page.get_by_label("用户名", exact=True)).to_be_visible()
            expect(page.get_by_label("密码", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="使用 Passkey 登录", exact=True)).to_have_count(0)
            expect(page.get_by_text("后端尚不支持 Passkey", exact=False)).to_be_visible()
            page.close()
        # A network/service error is NOT interpreted as a legacy backend.
        page = browser.new_page()
        page.route("**/api/v1/passkey/modes", lambda route: route.fulfill(
            status=503, content_type="application/json", body="{}"))
        page.goto(ORIGIN)
        expect(page.get_by_role("button", name="重新加载", exact=True)).to_be_visible()
        expect(page.get_by_label("密码", exact=True)).to_have_count(0)
        browser.close()
    print("Rolling upgrade legacy fallback and fail-closed network error UI passed")


if __name__ == "__main__":
    main()
