from django.db.models import Count, Q, Sum
from django.utils import timezone

from ..models import GymClass


def get_class_dashboard_summary(base_queryset):
    now = timezone.now()
    queryset = base_queryset

    by_discipline = list(
        queryset.values('discipline__name')
        .annotate(total=Count('id'))
        .order_by('-total', 'discipline__name')
    )
    by_status = list(
        queryset.values('status')
        .annotate(total=Count('id'))
        .order_by('status')
    )

    totals = queryset.aggregate(
        total_classes=Count('id'),
        total_capacity=Sum('capacity'),
        total_active_enrollments=Count('enrollments', filter=Q(enrollments__status='active')),
        upcoming_classes=Count('id', filter=Q(start_datetime__gte=now)),
    )

    total_capacity = totals.get('total_capacity') or 0
    total_enrollments = totals.get('total_active_enrollments') or 0
    occupancy = round((total_enrollments / total_capacity) * 100, 2) if total_capacity > 0 else 0

    return {
        'by_discipline': [
            {'discipline': item['discipline__name'] or 'Sin disciplina', 'total': item['total']}
            for item in by_discipline
        ],
        'by_status': [{'status': item['status'], 'total': item['total']} for item in by_status],
        'totals': {
            'total_classes': totals.get('total_classes') or 0,
            'upcoming_classes': totals.get('upcoming_classes') or 0,
            'total_capacity': total_capacity,
            'total_active_enrollments': total_enrollments,
            'occupancy_percent': occupancy,
        },
    }
