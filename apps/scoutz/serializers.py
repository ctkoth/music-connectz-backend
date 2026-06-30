from rest_framework import serializers
from .models import Prospect, ScoutingReport, Task

def _ser(m, flds):
    meta = type("Meta", (), {"model": m, "fields": flds, "read_only_fields": ["id", "created_at"]})
    return type(m.__name__ + "Serializer", (serializers.ModelSerializer,), {"Meta": meta})

ProspectSerializer = _ser(Prospect, ["id","handle","name","genre","source","stage","rating","notes","created_at","updated_at"])
ScoutingReportSerializer = _ser(ScoutingReport, ["id","prospect","summary","scores","body","created_at"])
TaskSerializer = _ser(Task, ["id","title","done","created_at"])


from .models import ScoutInterest, ScoutOpening, TalentListing  # noqa: E402

TalentListingSerializer = _ser(TalentListing, ["id","stage_name","genre","pitch","looking_for",
                                               "links","post_ref","open","created_at","updated_at"])
ScoutOpeningSerializer = _ser(ScoutOpening, ["id","label_or_company","title","looking_for",
                                             "body","open","created_at"])
ScoutInterestSerializer = _ser(ScoutInterest, ["id","listing","message","status","created_at"])
