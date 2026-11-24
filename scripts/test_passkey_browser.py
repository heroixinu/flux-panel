#!/usr/bin/env python3
"""End-to-end production frontend + actual backend using Chromium's virtual CTAP2 authenticator."""
import json
import urllib.request
from playwright.sync_api import sync_playwright, expect

ORIGIN = "http://localhost:4173"
USER = "ci_browser_admin"
PASSWORD = "ci-browser-new-password"


def post(path, data, token=None, success=True):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = token
    request = urllib.request.Request(ORIGIN + "/api/v1/" + path, json.dumps(data).encode(), headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.load(response)
    assert (result["code"] == 0) == success, (path, result["code"], result["msg"])
    return result.get("data")


def main():
    token = post("user/login", {"username": "admin_user", "password": "admin_user"})["token"]
    post("user/updatePassword", {"newUsername": USER, "currentPassword": "admin_user",
         "newPassword": PASSWORD, "confirmPassword": PASSWORD}, token)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(30000)
        page.on("dialog", lambda dialog: dialog.accept())
        cdp = context.new_cdp_session(page)
        cdp.send("WebAuthn.enable")
        authenticator = cdp.send("WebAuthn.addVirtualAuthenticator", {"options": {
            "protocol": "ctap2", "ctap2Version": "ctap2_1", "transport": "internal",
            "hasResidentKey": True, "hasUserVerification": True, "isUserVerified": True,
            "automaticPresenceSimulation": True}})["authenticatorId"]
        page.goto(ORIGIN)
        page.get_by_label("用户名", exact=True).fill(USER)
        page.get_by_label("密码", exact=True).fill(PASSWORD)
        page.get_by_role("button", name="登录", exact=True).click()
        page.wait_for_url("**/dashboard")

        page.goto(ORIGIN + "/passkeys")
        page.get_by_label("当前密码（可选）", exact=True).fill(PASSWORD)
        page.get_by_label("凭证名称", exact=True).fill("Browser CI credential")
        page.get_by_role("button", name="添加 Passkey", exact=True).click()
        expect(page.get_by_text("Browser CI credential", exact=True)).to_be_visible()
        credentials = cdp.send("WebAuthn.getCredentials", {"authenticatorId": authenticator})["credentials"]
        assert len(credentials) == 1 and credentials[0]["isResidentCredential"]
        page.get_by_role("button", name="验证已绑定的 Passkey", exact=True).click()
        expect(page.get_by_text("最近验证：", exact=False)).to_be_visible()
        page.get_by_role("button", name="关闭账密登录", exact=True).click()
        expect(page.get_by_text("账密登录：已关闭", exact=True)).to_be_visible()
        post("user/login", {"username": USER, "password": PASSWORD}, success=False)

        page.evaluate("localStorage.clear()")
        page.goto(ORIGIN)
        expect(page.get_by_role("button", name="使用 Passkey 登录", exact=True)).to_be_enabled()
        expect(page.get_by_label("用户名", exact=True)).to_have_count(0)
        expect(page.get_by_label("密码", exact=True)).to_have_count(0)
        page.get_by_role("button", name="使用 Passkey 登录", exact=True).click()
        page.wait_for_url("**/dashboard")
        assert page.evaluate("localStorage.getItem('name')") == USER

        page.goto(ORIGIN + "/passkeys")
        page.get_by_role("button", name="删除", exact=True).click()
        expect(page.get_by_text("仅 Passkey 登录时不能删除最后一个已验证的凭证", exact=True)).to_be_visible()
        expect(page.get_by_text("Browser CI credential", exact=True)).to_be_visible()
        page.get_by_role("button", name="恢复账密登录", exact=True).click()
        expect(page.get_by_text("账密登录：已开启", exact=True)).to_be_visible()
        post("user/login", {"username": USER, "password": PASSWORD})
        browser.close()
    print("Chromium UI registration, discoverable login, password form hiding, deletion protection and recovery passed")


if __name__ == "__main__":
    main()
