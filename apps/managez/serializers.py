from rest_framework import serializers

from .models import (Booking, Client, Contract, Deal, Invoice, Payout,
                     RosterArtist, Task)


def _ser(model_cls, flds):
    meta = type("Meta", (), {"model": model_cls, "fields": flds,
                             "read_only_fields": ["id", "created_at"]})
    return type(model_cls.__name__ + "Serializer", (serializers.ModelSerializer,), {"Meta": meta})


RosterArtistSerializer = _ser(RosterArtist, ["id", "name", "role", "status", "notes", "created_at"])
ClientSerializer = _ser(Client, ["id", "name", "company", "email", "notes", "created_at"])
ContractSerializer = _ser(Contract, ["id", "title", "party", "terms", "value", "status", "created_at"])
BookingSerializer = _ser(Booking, ["id", "title", "venue", "date", "fee", "status", "created_at"])
DealSerializer = _ser(Deal, ["id", "title", "stage", "value", "created_at"])
InvoiceSerializer = _ser(Invoice, ["id", "client", "amount", "status", "due_date", "created_at"])
PayoutSerializer = _ser(Payout, ["id", "payee", "amount", "status", "note", "created_at"])
TaskSerializer = _ser(Task, ["id", "title", "done", "due", "created_at"])
