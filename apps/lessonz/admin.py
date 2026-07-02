from django.contrib import admin

from .models import LessonBooking, LessonOffer, LessonPayment, TeacherSkillRating


@admin.register(TeacherSkillRating)
class TeacherSkillRatingAdmin(admin.ModelAdmin):
    list_display = ("user", "skill", "rating", "updated_at")
    search_fields = ("user__username", "skill")


@admin.register(LessonOffer)
class LessonOfferAdmin(admin.ModelAdmin):
    list_display = ("teacher", "skill", "title", "pricing_mode", "price", "city", "remote_ok", "rating_snapshot", "is_active")
    list_filter = ("pricing_mode", "remote_ok", "is_active", "skill")
    search_fields = ("teacher__username", "title", "city")


@admin.register(LessonBooking)
class LessonBookingAdmin(admin.ModelAdmin):
    list_display = ("offer", "student", "pricing_mode", "hours", "agreed_total", "status", "created_at")
    list_filter = ("status", "pricing_mode")
    search_fields = ("student__username", "offer__title")


@admin.register(LessonPayment)
class LessonPaymentAdmin(admin.ModelAdmin):
    list_display = ("booking", "payer", "payee", "amount", "currency", "settled", "created_at")
    list_filter = ("settled",)


from .models import LessonPost, LessonPostPurchase  # noqa: E402


@admin.register(LessonPost)
class LessonPostAdmin(admin.ModelAdmin):
    list_display = ("teacher", "skill", "title", "price", "visibility", "rating_snapshot", "is_active", "created_at")
    list_filter = ("visibility", "skill", "is_active")
    search_fields = ("teacher__username", "title")


@admin.register(LessonPostPurchase)
class LessonPostPurchaseAdmin(admin.ModelAdmin):
    list_display = ("post", "student", "amount", "currency", "settled", "created_at")
    list_filter = ("settled",)
    search_fields = ("student__username", "post__title")
