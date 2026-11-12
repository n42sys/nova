from django.urls import path

from core.api import views

org = "orgs/<slug:org>/"

urlpatterns = [
    path("me/", views.MeView.as_view(), name="me"),
    path(org, views.OrgDetailView.as_view(), name="org-detail"),
    path(f"{org}sites/", views.SiteListView.as_view(), name="site-list"),
    path(f"{org}sites/<uuid:site_id>/", views.SiteDetailView.as_view(), name="site-detail"),
    path(
        f"{org}sites/<uuid:site_id>/tokens/",
        views.ApiTokenListView.as_view(),
        name="api-token-list",
    ),
    path(
        f"{org}sites/<uuid:site_id>/tokens/<uuid:token_id>/",
        views.ApiTokenDetailView.as_view(),
        name="api-token-detail",
    ),
    path(f"{org}media/uploads/", views.MediaUploadView.as_view(), name="media-upload"),
    path(f"{org}media/", views.MediaListView.as_view(), name="media-list"),
    path(f"{org}media/<uuid:asset_id>/", views.MediaDetailView.as_view(), name="media-detail"),
    path(f"{org}members/", views.MemberListView.as_view(), name="member-list"),
    path(
        f"{org}members/<uuid:membership_id>/",
        views.MemberDetailView.as_view(),
        name="member-detail",
    ),
    path(
        f"{org}members/<uuid:membership_id>/site-roles/<uuid:site_id>/",
        views.MemberSiteRoleView.as_view(),
        name="member-site-role",
    ),
    path(f"{org}audit-log/", views.AuditLogView.as_view(), name="audit-log"),
    path(f"{org}invitations/", views.InvitationListView.as_view(), name="invitation-list"),
    path(
        f"{org}invitations/<uuid:invitation_id>/",
        views.InvitationDetailView.as_view(),
        name="invitation-detail",
    ),
    path(
        f"{org}invitations/<uuid:invitation_id>/resend/",
        views.InvitationResendView.as_view(),
        name="invitation-resend",
    ),
    path(
        "invitations/<str:token>/",
        views.InvitationPreviewView.as_view(),
        name="invitation-preview",
    ),
    path(
        "invitations/<str:token>/claim/",
        views.InvitationClaimView.as_view(),
        name="invitation-claim",
    ),
    path(
        "invitations/<str:token>/accept/",
        views.InvitationAcceptView.as_view(),
        name="invitation-accept",
    ),
]
