from rest_framework import serializers

from .models import LessonBooking, LessonOffer


class LessonOfferSerializer(serializers.ModelSerializer):
    teacher_username = serializers.CharField(source="teacher.username", read_only=True)
    distance_km = serializers.FloatField(read_only=True, required=False)

    class Meta:
        model = LessonOffer
        fields = (
            "id", "teacher_username", "persona", "skill", "title", "description",
            "pricing_mode", "price", "currency", "city", "latitude", "longitude",
            "remote_ok", "in_person_ok", "callz_ok", "rating_snapshot", "is_active",
            "created_at", "distance_km",
        )
        read_only_fields = ("id", "teacher_username", "rating_snapshot", "created_at", "distance_km")


class LessonBookingSerializer(serializers.ModelSerializer):
    offer_title = serializers.CharField(source="offer.title", read_only=True)
    teacher_username = serializers.CharField(source="offer.teacher.username", read_only=True)
    student_username = serializers.CharField(source="student.username", read_only=True)

    class Meta:
        model = LessonBooking
        fields = (
            "id", "offer", "offer_title", "teacher_username", "student_username",
            "pricing_mode", "hours", "agreed_total", "currency", "status", "method", "note",
            "created_at",
        )
        read_only_fields = ("id", "agreed_total", "currency", "status", "created_at",
                            "offer_title", "teacher_username", "student_username")


from .models import LessonPost, LessonPostPurchase  # noqa: E402


class LessonPostSerializer(serializers.ModelSerializer):
    teacher_username = serializers.CharField(source="teacher.username", read_only=True)
    unlocked = serializers.SerializerMethodField()
    media_ref = serializers.SerializerMethodField()

    class Meta:
        model = LessonPost
        fields = (
            "id", "teacher_username", "persona", "skill", "title", "description",
            "preview_ref", "media_ref", "price", "currency", "visibility",
            "rating_snapshot", "is_active", "created_at", "unlocked",
        )
        read_only_fields = ("id", "teacher_username", "rating_snapshot", "created_at",
                            "unlocked", "media_ref")

    def _user(self):
        req = self.context.get("request")
        return getattr(req, "user", None)

    def get_unlocked(self, obj):
        u = self._user()
        if not u or not u.is_authenticated:
            return False
        if obj.teacher_id == u.id:
            return True
        return LessonPostPurchase.objects.filter(post=obj, student=u).exists()

    def get_media_ref(self, obj):
        # Full media only after unlock (teacher always sees own).
        return obj.media_ref if self.get_unlocked(obj) else ""


class LessonPostCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = LessonPost
        fields = ("persona", "skill", "title", "description", "media_ref",
                  "preview_ref", "price", "currency", "visibility")
