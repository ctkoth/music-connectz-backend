from django.contrib import admin

from .models import (BodieZItem, BodyMetric, Exercise, FitnessGoal, GymLocation,
                     Routine, RoutineExercise, WorkoutSession, WorkoutSet)


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ("name", "muscle", "pattern", "difficulty", "owner")
    list_filter = ("muscle", "pattern", "difficulty")
    search_fields = ("name", "key")


class RoutineExerciseInline(admin.TabularInline):
    model = RoutineExercise
    extra = 0


@admin.register(Routine)
class RoutineAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "goal", "split", "bucket", "is_public", "updated_at")
    list_filter = ("goal", "split", "bucket", "is_public")
    inlines = [RoutineExerciseInline]


@admin.register(WorkoutSession)
class WorkoutSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "status", "started_at", "ended_at")
    list_filter = ("status",)


admin.site.register([WorkoutSet, BodyMetric, FitnessGoal, GymLocation, BodieZItem])
