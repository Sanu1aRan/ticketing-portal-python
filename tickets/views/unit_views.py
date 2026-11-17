"""
/api/units   (UnitController.java)

Units are the ICT Directorate sections (AsyHub, Functional, ...).
Any logged-in user can list them; only an admin can add or delete.
"""

from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..models import Unit
from ..security import ServiceError
from ..serializers import unit_json
from .common import body_param, validate_admin


@api_view(["GET", "POST"])
def units(request):
    if request.method == "POST":
        return add_unit(request)
    return get_all_units(request)


def get_all_units(request):
    return Response([unit_json(u) for u in Unit.objects.order_by("name")])


def add_unit(request):
    validate_admin(request.user)
    name = body_param(request, "name")
    if name is None or name.strip() == "":
        raise ServiceError("Unit name is required")
    name = name.strip()
    if len(name) > 100:
        raise ServiceError("Unit name is too long")
    if Unit.objects.filter(name=name).exists():
        raise ServiceError("Unit already exists")
    unit = Unit.objects.create(name=name)
    return Response({"message": "Unit added successfully", "unit": unit_json(unit)}, status=201)


@api_view(["DELETE"])
def delete_unit(request, unit_id):
    validate_admin(request.user)
    unit = Unit.objects.filter(pk=unit_id).first()
    if unit is None:
        raise ServiceError("Unit not found")
    unit.delete()
    return Response({"message": "Unit deleted successfully"})
