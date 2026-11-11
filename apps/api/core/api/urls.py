from django.urls import path

from core.api import views

org = "orgs/<slug:org>/"

urlpatterns = [
    path("me/", views.MeView.as_view(), name="me"),
    path(org, views.OrgDetailView.as_view(), name="org-detail"),
    path(f"{org}sites/", views.SiteListView.as_view(), name="site-list"),
    path(f"{org}sites/<uuid:site_id>/", views.SiteDetailView.as_view(), name="site-detail"),
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
]
