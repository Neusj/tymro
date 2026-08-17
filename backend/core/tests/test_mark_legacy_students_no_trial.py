from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone


@pytest.mark.django_db
def test_command_marks_only_eligible_students_before_cutoff(make_organization, make_user):
    org = make_organization()
    other_org = make_organization()
    cutoff = timezone.now()

    legacy = make_user('legacy', organization=org, role='student', trial_eligible=True)
    new_student = make_user('new-student', organization=org, role='student', trial_eligible=True)
    already_blocked = make_user('blocked', organization=org, role='student', trial_eligible=False)
    teacher = make_user('teacher', organization=org, role='teacher', trial_eligible=True)
    other_org_student = make_user('other-legacy', organization=other_org, role='student', trial_eligible=True)

    legacy.date_joined = cutoff - timedelta(days=2)
    legacy.save(update_fields=['date_joined'])
    already_blocked.date_joined = cutoff - timedelta(days=2)
    already_blocked.save(update_fields=['date_joined'])
    teacher.date_joined = cutoff - timedelta(days=2)
    teacher.save(update_fields=['date_joined'])
    other_org_student.date_joined = cutoff - timedelta(days=2)
    other_org_student.save(update_fields=['date_joined'])
    new_student.date_joined = cutoff + timedelta(minutes=1)
    new_student.save(update_fields=['date_joined'])

    out = StringIO()
    call_command(
        'mark_legacy_students_no_trial',
        before=cutoff.isoformat(),
        org_id=org.id,
        stdout=out,
    )

    legacy.refresh_from_db()
    new_student.refresh_from_db()
    already_blocked.refresh_from_db()
    teacher.refresh_from_db()
    other_org_student.refresh_from_db()

    assert legacy.trial_eligible is False
    assert new_student.trial_eligible is True
    assert already_blocked.trial_eligible is False
    assert teacher.trial_eligible is True
    assert other_org_student.trial_eligible is True
    assert 'Alumnos marcados sin clase gratis: 1' in out.getvalue()


@pytest.mark.django_db
def test_command_dry_run_does_not_change_students(make_organization, make_user):
    org = make_organization()
    cutoff = timezone.now()
    legacy = make_user('legacy-dry', organization=org, role='student', trial_eligible=True)
    legacy.date_joined = cutoff - timedelta(days=2)
    legacy.save(update_fields=['date_joined'])

    out = StringIO()
    call_command(
        'mark_legacy_students_no_trial',
        before=cutoff.isoformat(),
        dry_run=True,
        stdout=out,
    )

    legacy.refresh_from_db()
    assert legacy.trial_eligible is True
    assert 'DRY-RUN: no se modificaron alumnos.' in out.getvalue()
