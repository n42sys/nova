from django.core.management.base import BaseCommand, CommandError, CommandParser

from core.exceptions import ValidationFailed
from core.services.bootstrap import DEFAULT_FEATURES, bootstrap_organization

OWNER_MESSAGES = {
    "owner_exists": "{email} is already an owner; no invitation sent.",
    "invitation_sent": "Owner invitation emailed to {email}.",
    "invitation_pending": (
        "An owner invitation for {email} is still open; none sent. Use --resend for a new link."
    ),
    "invitation_resent": "A fresh owner invitation link was emailed to {email}.",
}


def _site(value: str) -> tuple[str, str]:
    name, sep, slug = value.rpartition(":")
    if not sep:
        raise CommandError(f'--site must look like "Name:slug", got {value!r}')
    return name, slug


class Command(BaseCommand):
    help = (
        "Create an organization with its sites and invite its owner. Safe to re-run: nothing "
        'is duplicated. Example: bootstrap_org --name "Culture & Interest" '
        '--slug culture-interest --owner-email owner@example.com --site "Main:main"'
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--name", required=True, help="Organization name.")
        parser.add_argument("--slug", required=True, help="Organization slug (URL name).")
        parser.add_argument("--owner-email", required=True, help="Who to invite as owner.")
        parser.add_argument(
            "--site",
            action="append",
            required=True,
            metavar="NAME:SLUG",
            help='A site to create, e.g. "Main:main". Repeat for more sites.',
        )
        parser.add_argument(
            "--features",
            default=",".join(DEFAULT_FEATURES),
            help=f"Comma-separated modules to turn on (default: {','.join(DEFAULT_FEATURES)}).",
        )
        parser.add_argument(
            "--resend",
            action="store_true",
            help="Email a fresh link if an owner invitation is already open.",
        )

    def handle(self, *args, **options) -> None:
        features = [f.strip() for f in options["features"].split(",") if f.strip()]
        try:
            result = bootstrap_organization(
                name=options["name"],
                slug=options["slug"],
                owner_email=options["owner_email"],
                sites=[_site(value) for value in options["site"]],
                features=features,
                resend=options["resend"],
            )
        except ValidationFailed as exc:
            raise CommandError(f"{exc.message} {exc.details}") from None

        org = result.organization
        write = self.stdout.write
        if result.org_created:
            write(self.style.SUCCESS(f"Created organization {org.name} ({org.slug})."))
        else:
            write(f"Organization {org.name} ({org.slug}) already exists.")
            if result.name_differs:
                write(self.style.WARNING(f"  Kept its name {org.name!r}; --name was ignored."))
        if result.features_added:
            write(self.style.SUCCESS(f"  Turned on features: {', '.join(result.features_added)}."))
        if result.sites_created:
            write(self.style.SUCCESS(f"  Created sites: {', '.join(result.sites_created)}."))
        if result.sites_existing:
            write(f"  Sites already present: {', '.join(result.sites_existing)}.")
        owner_email = options["owner_email"].strip().lower()
        write(OWNER_MESSAGES[result.owner].format(email=owner_email))
