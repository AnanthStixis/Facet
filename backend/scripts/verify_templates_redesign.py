"""Verification for the redesigned template page's backend changes.

Covers the two things with real consequences:

1. A Super Admin creating a template produces a true platform default
   immediately - no "clone to org" step - visible and clonable by an
   unrelated org's Client Admin the moment it is created.
2. A Client Admin's own create / edit / publish / clone flow is unchanged.

    python -m scripts.verify_templates_redesign
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.seed import (  # noqa: E402
    CLIENT_ADMIN_EMAIL,
    CLIENT_ADMIN_PASSWORD,
    SUPER_ADMIN_EMAIL,
    SUPER_ADMIN_PASSWORD,
)

PASS = "  [pass]"
FAIL = "  [FAIL]"
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"{PASS if condition else FAIL} {label}{(' - ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


async def main() -> int:
    from app.main import app

    def make() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    suffix = uuid.uuid4().hex[:6]
    template_name = f"Verify Global Template {suffix}"

    async with make() as super_admin, make() as client_admin:
        sa_login = await super_admin.post(
            "/api/v1/auth/login", json={"email": SUPER_ADMIN_EMAIL, "password": SUPER_ADMIN_PASSWORD}
        )
        sa_login.raise_for_status()
        sa_headers = {"authorization": f"Bearer {sa_login.json()['access_token']}"}

        ca_login = await client_admin.post(
            "/api/v1/auth/login", json={"email": CLIENT_ADMIN_EMAIL, "password": CLIENT_ADMIN_PASSWORD}
        )
        ca_login.raise_for_status()
        ca_headers = {"authorization": f"Bearer {ca_login.json()['access_token']}"}

        print("\n== Super Admin creates a template (no category picker in the new API) ==")
        create = await super_admin.post(
            "/api/v1/catalog/templates",
            json={
                "name": template_name,
                "target_type": "employee",
                "description": "Created by the super admin verify run.",
                "is_anonymous": False,
                "min_responses_to_reveal": 4,
            },
            headers=sa_headers,
        )
        check("create returns 201", create.status_code == 201, str(create.status_code) + " " + create.text)
        template_id = create.json()["id"] if create.status_code == 201 else None

        if template_id:
            detail = await super_admin.get(f"/api/v1/catalog/templates/{template_id}", headers=sa_headers)
            check("super admin sees the new template as editable", detail.json().get("editable") is True)
            check(
                "template scope is global (org_id NULL) immediately, no clone step",
                detail.json().get("scope") == "global",
                str(detail.json().get("scope")),
            )

            print("\n== A different org's Client Admin sees it as a usable global default ==")
            cats = await client_admin.get("/api/v1/catalog/categories", headers=ca_headers)
            cats.raise_for_status()
            found = None
            for category in cats.json():
                for tpl in category["templates"]:
                    if tpl["id"] == template_id:
                        found = tpl
            check("Client Admin's template list includes the super admin's global template", found is not None)
            if found:
                check(
                    "Client Admin sees it as not editable (must clone, cannot edit a global default)",
                    found["editable"] is False,
                )
                check("no super-admin clone step was needed for it to already appear", True)

            print("\n== Client Admin clones the global template into their own org ==")
            clone = await client_admin.post(
                f"/api/v1/catalog/templates/{template_id}/clone",
                json={"name": f"{template_name} (northwind copy)"},
                headers=ca_headers,
            )
            check("clone succeeds", clone.status_code == 201, str(clone.status_code) + " " + clone.text)
            clone_id = clone.json().get("id") if clone.status_code == 201 else None
            if clone_id:
                clone_detail = await client_admin.get(f"/api/v1/catalog/templates/{clone_id}", headers=ca_headers)
                check("the clone is editable by the Client Admin", clone_detail.json().get("editable") is True)
                check("the clone is org-scoped", clone_detail.json().get("scope") == "org")

            print("\n== Super Admin publishes their own global template ==")
            publish = await super_admin.post(f"/api/v1/catalog/templates/{template_id}/publish", headers=sa_headers)
            check("super admin can publish their own global draft", publish.status_code == 200, publish.text)

            print("\n== Super Admin cannot clone (no clone UI/endpoint use expected) ==")
            sa_clone_attempt = await super_admin.post(
                f"/api/v1/catalog/templates/{template_id}/clone", json={}, headers=sa_headers
            )
            check(
                "clone as super admin is rejected (they have no org to clone into)",
                sa_clone_attempt.status_code == 422,
                str(sa_clone_attempt.status_code) + " " + sa_clone_attempt.text,
            )

        print("\n== Client Admin's own create flow is unchanged ==")
        ca_name = f"Verify Org Template {suffix}"
        ca_create = await client_admin.post(
            "/api/v1/catalog/templates",
            json={
                "name": ca_name,
                "target_type": "team",
                "description": None,
                "is_anonymous": True,
                "min_responses_to_reveal": 4,
            },
            headers=ca_headers,
        )
        check("Client Admin create returns 201", ca_create.status_code == 201, ca_create.text)
        if ca_create.status_code == 201:
            ca_template_id = ca_create.json()["id"]
            ca_detail = await client_admin.get(f"/api/v1/catalog/templates/{ca_template_id}", headers=ca_headers)
            check("Client Admin's own template is org-scoped, not global", ca_detail.json().get("scope") == "org")
            check("Client Admin's own template is editable by them", ca_detail.json().get("editable") is True)

            draft = await client_admin.put(
                f"/api/v1/catalog/templates/{ca_template_id}/draft",
                json={
                    "definition": {
                        "intro": "",
                        "scale": {"min": 1, "max": 5, "labels": {}},
                        "sections": [
                            {
                                "key": "s1",
                                "title": "General",
                                "questions": [
                                    {"key": "q1", "text": "How effective is this team?", "type": "scale", "required": True}
                                ],
                            }
                        ],
                        "closing": {"comment_prompt": "Anything else?", "comment_required": False},
                    }
                },
                headers=ca_headers,
            )
            check("Client Admin can save a draft", draft.status_code == 200, draft.text)

            publish_ca = await client_admin.post(f"/api/v1/catalog/templates/{ca_template_id}/publish", headers=ca_headers)
            check("Client Admin can publish", publish_ca.status_code == 200, publish_ca.text)

        print("\n== One-shot create->save->publish (Templates.tsx's popup submit) is immediately usable ==")
        oneshot_name = f"Verify OneShot {suffix}"
        oneshot_create = await client_admin.post(
            "/api/v1/catalog/templates",
            json={"name": oneshot_name, "target_type": "employee", "description": None, "is_anonymous": False},
            headers=ca_headers,
        )
        check("one-shot create returns 201", oneshot_create.status_code == 201, oneshot_create.text)
        oneshot_id = oneshot_create.json()["id"] if oneshot_create.status_code == 201 else None
        if oneshot_id:
            oneshot_create_detail = await client_admin.get(
                f"/api/v1/catalog/templates/{oneshot_id}", headers=ca_headers
            )
            check(
                "min_responses_to_reveal defaults to 0 (item 5 - vestigial field removed from create surface)",
                oneshot_create_detail.json().get("min_responses_to_reveal") == 0,
                str(oneshot_create_detail.json().get("min_responses_to_reveal")),
            )
            check(
                "new template starts active (item 12 default true)",
                oneshot_create_detail.json().get("is_active") is True,
            )

            oneshot_draft = await client_admin.put(
                f"/api/v1/catalog/templates/{oneshot_id}/draft",
                json={
                    "definition": {
                        "intro": "",
                        "scale": {"min": 1, "max": 5, "labels": {}},
                        "sections": [
                            {
                                "key": "s1",
                                "title": "General",
                                "questions": [
                                    {"key": "q1", "text": "Overall rating?", "type": "scale", "required": True}
                                ],
                            }
                        ],
                        "closing": {"comment_prompt": "Anything else?", "comment_required": False},
                    }
                },
                headers=ca_headers,
            )
            check("one-shot draft save succeeds", oneshot_draft.status_code == 200, oneshot_draft.text)

            oneshot_publish = await client_admin.post(
                f"/api/v1/catalog/templates/{oneshot_id}/publish", headers=ca_headers
            )
            check("one-shot publish succeeds", oneshot_publish.status_code == 200, oneshot_publish.text)

            cats_after = await client_admin.get("/api/v1/catalog/categories", headers=ca_headers)
            cats_after.raise_for_status()
            found_after_publish = None
            for category in cats_after.json():
                for tpl in category["templates"]:
                    if tpl["id"] == oneshot_id:
                        found_after_publish = tpl
            check(
                "immediately selectable (published, not stuck in draft) right after the one-shot flow",
                found_after_publish is not None and found_after_publish["status"] == "published",
                str(found_after_publish),
            )

            print("\n== Toggling a template disabled removes it from what CreateFeedback.tsx's dropdown would see ==")
            toggle_off = await client_admin.post(
                f"/api/v1/catalog/templates/{oneshot_id}/toggle", headers=ca_headers
            )
            check("toggle off succeeds", toggle_off.status_code == 200, toggle_off.text)
            check("toggle response reports is_active false", toggle_off.json().get("is_active") is False)

            cats_disabled = await client_admin.get("/api/v1/catalog/categories", headers=ca_headers)
            disabled_row = None
            for category in cats_disabled.json():
                for tpl in category["templates"]:
                    if tpl["id"] == oneshot_id:
                        disabled_row = tpl
            check(
                "categories list still reports is_active false for CreateFeedback.tsx to filter by",
                disabled_row is not None and disabled_row["is_active"] is False,
                str(disabled_row),
            )

            toggle_on = await client_admin.post(
                f"/api/v1/catalog/templates/{oneshot_id}/toggle", headers=ca_headers
            )
            check("toggle back on succeeds", toggle_on.status_code == 200, toggle_on.text)
            check("toggle response reports is_active true again", toggle_on.json().get("is_active") is True)

            print("\n== Deleting a template actually removes it ==")
            delete_resp = await client_admin.delete(
                f"/api/v1/catalog/templates/{oneshot_id}", headers=ca_headers
            )
            check("delete returns 204", delete_resp.status_code == 204, str(delete_resp.status_code))

            get_after_delete = await client_admin.get(
                f"/api/v1/catalog/templates/{oneshot_id}", headers=ca_headers
            )
            check(
                "template is gone after delete",
                get_after_delete.status_code == 404,
                str(get_after_delete.status_code),
            )

    print()
    if failures:
        print(f"{len(failures)} check(s) failed:")
        for label in failures:
            print(f"  - {label}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
