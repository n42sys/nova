import io
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from core.models import AuditLog, MediaAsset, Role
from core.tasks import purge_stale_uploads, read_image_dimensions
from core.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
    SiteFactory,
    SiteRoleFactory,
)
from nova.celery import app as celery_app

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("s3")]


@pytest.fixture
def org():
    return OrganizationFactory()


@pytest.fixture
def site(org):
    return SiteFactory(organization=org, slug="main")


def _member(browser, org, org_role=None, site_roles=None):
    membership = MembershipFactory(organization=org, org_role=org_role)
    for site, role in (site_roles or {}).items():
        SiteRoleFactory(membership=membership, site=site, role=role)
    browser.force_login(membership.user)
    return membership


def _png(width=3, height=2) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(buffer, format="PNG")
    return buffer.getvalue()


def _request(browser, org, *, filename="poster.png", mime_type="image/png", size=None, site=None):
    body = {"filename": filename, "mime_type": mime_type, "size_bytes": size or len(_png())}
    if site is not None:
        body["site_id"] = str(site.id)
    return browser.send("post", reverse("media-upload", kwargs={"org": org.slug}), body)


def _put(s3, asset_key, body: bytes, content_type="image/png"):
    s3.put_object(Bucket=settings.R2_BUCKET, Key=asset_key, Body=body, ContentType=content_type)


def _confirm(browser, org, asset_id, alt_text=""):
    return browser.send(
        "post",
        reverse("media-list", kwargs={"org": org.slug}),
        {"asset_id": str(asset_id), "alt_text": alt_text},
    )


def _upload(
    browser, org, s3, *, site=None, body=None, mime_type="image/png", filename="poster.png"
):
    body = body if body is not None else _png()
    response = _request(
        browser, org, filename=filename, mime_type=mime_type, size=len(body), site=site
    )
    assert response.status_code == 201, response.content
    data = response.json()
    _put(s3, data["file_key"], body, mime_type)
    confirmed = _confirm(browser, org, data["asset_id"])
    assert confirmed.status_code == 200, confirmed.content
    return MediaAsset.objects.for_org(org).get(id=data["asset_id"])


def _list(browser, org, **params):
    url = reverse("media-list", kwargs={"org": org.slug})
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return browser.get(f"{url}?{query}" if query else url)


def _detail_url(asset):
    return reverse("media-detail", kwargs={"org": asset.organization.slug, "asset_id": asset.id})


# Upload request


def test_upload_request_creates_pending_asset_and_presigned_put(browser, org, site):
    member = _member(browser, org, Role.EDITOR)

    response = _request(browser, org, filename="Poster Final.PNG", site=site)

    assert response.status_code == 201
    data = response.json()
    asset = MediaAsset.objects.for_org(org).get(id=data["asset_id"])
    assert asset.status == MediaAsset.Status.PENDING
    assert (asset.site, asset.uploaded_by, asset.mime_type) == (site, member.user, "image/png")
    assert data["file_key"] == asset.file_key == f"orgs/{org.id}/{asset.id}/Poster-Final.PNG"
    assert data["method"] == "PUT"
    assert data["headers"] == {"Content-Type": "image/png"}
    query = parse_qs(urlparse(data["upload_url"]).query)
    assert query["X-Amz-Expires"] == ["900"]
    assert "content-type" in query["X-Amz-SignedHeaders"][0].split(";")
    assert urlparse(data["upload_url"]).path.endswith(asset.file_key)
    expires_in = datetime.fromisoformat(data["expires_at"]) - timezone.now()
    assert timedelta(minutes=14) < expires_in <= timedelta(minutes=15)
    assert AuditLog.objects.for_org(org).filter(action="media.upload_request").count() == 1


@pytest.mark.parametrize(
    "filename",
    [
        "../../etc/passwd",
        "..\\..\\windows\\system32",
        "/abs/path.png",
        "a b/c d.png",
        "...",
        "ü.png",
    ],
)
def test_keys_are_always_under_the_callers_org_prefix(browser, org, site, filename):
    _member(browser, org, Role.OWNER)
    other_org = OrganizationFactory()

    response = _request(browser, org, filename=filename, site=site)

    assert response.status_code == 201
    key = response.json()["file_key"]
    asset_id = response.json()["asset_id"]
    assert key.startswith(f"orgs/{org.id}/{asset_id}/")
    assert ".." not in key.split("/") and "\\" not in key
    assert str(other_org.id) not in key
    assert len(key.split("/")) == 4


@pytest.mark.parametrize(
    "mime_type", ["image/svg+xml", "text/html", "application/x-msdownload", "application/zip", ""]
)
def test_disallowed_type_is_rejected(browser, org, mime_type):
    _member(browser, org, Role.OWNER)

    response = _request(browser, org, mime_type=mime_type, size=10)

    assert response.status_code == 400
    assert not MediaAsset.objects.for_org(org).exists()


@override_settings(NOVA_MEDIA_MAX_BYTES=1000)
def test_oversize_is_rejected(browser, org):
    _member(browser, org, Role.OWNER)

    assert _request(browser, org, size=1001).status_code == 400
    assert _request(browser, org, size=1000).status_code == 201
    assert MediaAsset.objects.for_org(org).count() == 1


def test_default_max_is_25_mb(browser, org):
    _member(browser, org, Role.OWNER)

    assert settings.NOVA_MEDIA_MAX_BYTES == 25 * 1024 * 1024
    assert _request(browser, org, size=25 * 1024 * 1024 + 1).status_code == 400


def test_event_staff_cannot_upload(browser, org, site):
    _member(browser, org, Role.EVENT_STAFF)

    assert _request(browser, org, site=site).status_code == 403


def test_site_editor_uploads_only_to_their_site(browser, org, site):
    other = SiteFactory(organization=org, slug="events")
    _member(browser, org, None, {site: Role.EDITOR})

    assert _request(browser, org, site=site).status_code == 201
    assert _request(browser, org, site=other).status_code == 404  # not visible to them
    assert _request(browser, org).status_code == 403  # org-wide needs an org role


# Confirm


def test_confirm_marks_ready_and_reads_image_dimensions(
    browser, org, site, s3, django_capture_on_commit_callbacks
):
    _member(browser, org, Role.EDITOR)
    data = _request(browser, org, site=site, size=len(_png(5, 4))).json()
    _put(s3, data["file_key"], _png(5, 4))

    with django_capture_on_commit_callbacks(execute=True):
        response = _confirm(browser, org, data["asset_id"], alt_text="A red square")

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["alt_text"]) == ("ready", "A red square")
    assert body["url"] == f"{settings.R2_PUBLIC_URL}/{data['file_key']}"
    asset = MediaAsset.objects.for_org(org).get(id=data["asset_id"])
    assert (asset.status, asset.width, asset.height) == (MediaAsset.Status.READY, 5, 4)
    assert AuditLog.objects.for_org(org).filter(action="media.create").count() == 1


def test_confirm_fails_if_the_object_is_missing(browser, org):
    _member(browser, org, Role.EDITOR)
    data = _request(browser, org).json()

    response = _confirm(browser, org, data["asset_id"])

    assert response.status_code == 400
    assert MediaAsset.objects.for_org(org).get(id=data["asset_id"]).status == "pending"


@pytest.mark.parametrize(
    ("body", "content_type"),
    [(b"short", "image/png"), (None, "image/jpeg")],
    ids=["wrong-size", "wrong-type"],
)
def test_confirm_with_wrong_size_or_type_deletes_object_and_asset(
    browser, org, s3, body, content_type
):
    _member(browser, org, Role.EDITOR)
    data = _request(browser, org).json()
    _put(s3, data["file_key"], body if body is not None else _png(), content_type)

    response = _confirm(browser, org, data["asset_id"])

    assert response.status_code == 400
    assert not MediaAsset.objects.for_org(org).filter(id=data["asset_id"]).exists()
    assert "Contents" not in s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=data["file_key"])
    assert AuditLog.objects.for_org(org).filter(action="media.upload_rejected").count() == 1


def test_confirm_twice_is_a_no_op(browser, org, s3):
    _member(browser, org, Role.EDITOR)
    asset = _upload(browser, org, s3)

    assert _confirm(browser, org, asset.id).status_code == 200
    assert AuditLog.objects.for_org(org).filter(action="media.create").count() == 1


def test_confirm_unknown_or_deleting_asset_is_404(browser, org, s3):
    _member(browser, org, Role.OWNER)
    asset = _upload(browser, org, s3)
    MediaAsset.objects.for_org(org).filter(id=asset.id).update(status=MediaAsset.Status.DELETING)

    assert _confirm(browser, org, asset.id).status_code == 404
    assert _confirm(browser, org, OrganizationFactory().id).status_code == 404


def test_non_image_uploaded_as_png_becomes_invalid(
    browser, org, s3, caplog, django_capture_on_commit_callbacks
):
    _member(browser, org, Role.EDITOR)
    body = b"MZ\x90\x00 definitely not a png"
    data = _request(browser, org, size=len(body)).json()
    _put(s3, data["file_key"], body, "image/png")

    with django_capture_on_commit_callbacks(execute=True):  # runs the dimensions task
        response = _confirm(browser, org, data["asset_id"])

    assert response.status_code == 200  # size and type matched; the content is checked after
    asset = MediaAsset.objects.for_org(org).get(id=data["asset_id"])
    assert (asset.status, asset.width, asset.height) == (MediaAsset.Status.INVALID, None, None)
    assert "Contents" not in s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=asset.file_key)
    assert any(
        str(asset.id) in record.getMessage() and "invalid" in record.getMessage()
        for record in caplog.records
    )
    assert _list(browser, org).json()["results"] == []
    assert browser.send("patch", _detail_url(asset), {"alt_text": "x"}).status_code == 404


def test_dimensions_task_leaves_valid_images_ready(browser, org, s3):
    _member(browser, org, Role.EDITOR)
    asset = _upload(browser, org, s3)

    read_image_dimensions(str(org.id), str(asset.id))

    asset.refresh_from_db()
    assert (asset.status, asset.width, asset.height) == (MediaAsset.Status.READY, 3, 2)


# List


def test_list_shows_only_ready_assets_with_filters(browser, org, site, s3):
    events = SiteFactory(organization=org, slug="events")
    _member(browser, org, Role.OWNER)
    poster = _upload(browser, org, s3, site=site)
    clip = _upload(browser, org, s3, site=events, body=b"0" * 10, mime_type="video/mp4")
    pdf = _upload(browser, org, s3, body=b"%PDF-1", mime_type="application/pdf")
    _request(browser, org, site=site)  # pending: never listed

    def ids(**params):
        response = _list(browser, org, **params)
        assert response.status_code == 200, response.content
        return [item["id"] for item in response.json()["results"]]

    assert ids() == [str(pdf.id), str(clip.id), str(poster.id)]
    assert ids(site_id=site.id) == [str(poster.id)]
    assert ids(mime_prefix="video/") == [str(clip.id)]
    assert ids(mime_prefix="image") == [str(poster.id)]

    first = _list(browser, org, limit=2).json()
    second = _list(browser, org, limit=2, cursor=first["next_cursor"]).json()
    assert [i["id"] for i in first["results"] + second["results"]] == ids()
    assert second["next_cursor"] is None


def test_site_editor_sees_only_their_sites_media(browser, org, site, s3):
    events = SiteFactory(organization=org, slug="events")
    _member(browser, org, Role.OWNER)
    mine = _upload(browser, org, s3, site=site)
    _upload(browser, org, s3, site=events)
    _upload(browser, org, s3)  # org-wide
    _member(browser, org, None, {site: Role.EDITOR})

    response = _list(browser, org)

    assert [item["id"] for item in response.json()["results"]] == [str(mine.id)]
    assert _list(browser, org, site_id=events.id).status_code == 404


def test_event_staff_cannot_list_media(browser, org):
    _member(browser, org, Role.EVENT_STAFF)

    assert _list(browser, org).status_code == 403


def test_bad_list_params_are_400(browser, org):
    _member(browser, org, Role.OWNER)

    assert _list(browser, org, limit=0).status_code == 400
    assert _list(browser, org, cursor="junk").status_code == 400


# Update and delete


def test_editor_updates_alt_text(browser, org, s3):
    _member(browser, org, Role.EDITOR)
    asset = _upload(browser, org, s3)

    response = browser.send("patch", _detail_url(asset), {"alt_text": "Listening party poster"})

    assert response.status_code == 200
    assert response.json()["alt_text"] == "Listening party poster"
    entry = AuditLog.objects.for_org(org).get(action="media.update")
    assert entry.metadata["changes"]["alt_text"]["to"] == "Listening party poster"


def test_editor_can_upload_but_not_delete(browser, org, s3):
    _member(browser, org, Role.EDITOR)
    asset = _upload(browser, org, s3)

    assert browser.send("delete", _detail_url(asset)).status_code == 403
    assert MediaAsset.objects.for_org(org).get(id=asset.id).status == MediaAsset.Status.READY


def test_admin_delete_hides_asset_then_task_removes_object_and_row(
    browser, org, s3, django_capture_on_commit_callbacks
):
    _member(browser, org, Role.ADMIN)
    asset = _upload(browser, org, s3)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        assert browser.send("delete", _detail_url(asset)).status_code == 204
    assert MediaAsset.objects.for_org(org).get(id=asset.id).status == MediaAsset.Status.DELETING
    assert _list(browser, org).json()["results"] == []
    assert browser.send("patch", _detail_url(asset), {"alt_text": "x"}).status_code == 404

    for callback in callbacks:
        callback()

    assert not MediaAsset.objects.for_org(org).filter(id=asset.id).exists()
    assert "Contents" not in s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=asset.file_key)
    assert AuditLog.objects.for_org(org).filter(action="media.delete").count() == 1


# Cleanup of stale pending uploads


def test_purge_removes_only_pending_uploads_older_than_a_day(browser, org, s3):
    _member(browser, org, Role.OWNER)
    stale = _request(browser, org).json()
    fresh = _request(browser, org).json()
    _put(s3, stale["file_key"], _png())
    ready = _upload(browser, org, s3)
    MediaAsset.objects.for_org(org).filter(id__in=[stale["asset_id"], ready.id]).update(
        created_at=timezone.now() - timedelta(hours=25)
    )

    assert purge_stale_uploads() == 1

    remaining = set(MediaAsset.objects.for_org(org).values_list("id", flat=True))
    assert remaining == {ready.id, MediaAsset.objects.for_org(org).get(id=fresh["asset_id"]).id}
    assert "Contents" not in s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=stale["file_key"])


def test_purge_runs_daily_on_beat():
    entry = settings.CELERY_BEAT_SCHEDULE["purge-stale-media-uploads"]

    assert entry["task"] == "core.tasks.purge_stale_uploads"
    assert entry["task"] in celery_app.tasks
    assert entry["schedule"].hour == {3} and entry["schedule"].minute == {0}
