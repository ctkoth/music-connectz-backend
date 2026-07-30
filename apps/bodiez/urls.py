from django.urls import path

from .views import (AIRoutineView, BodyMapView, CatalogView, CoachView,
                    ExercisesView, GoalsView, ItemDetailView, ItemsView,
                    LocationDetailView, LocationsView, MetricsView,
                    ProgressView, RoutineDetailView, RoutineExercisesView,
                    RoutinesView, SessionFinishView, SessionSetsView,
                    SessionsView)

urlpatterns = [
    path("catalog/", CatalogView.as_view(), name="bodiez-catalog"),
    path("exercises/", ExercisesView.as_view(), name="bodiez-exercises"),
    # `routines/ai/` before `routines/<pk>/` — "ai" is not an int, but keeping
    # the fixed route first documents the intent rather than relying on it.
    path("routines/ai/", AIRoutineView.as_view(), name="bodiez-routine-ai"),
    path("routines/", RoutinesView.as_view(), name="bodiez-routines"),
    path("routines/<int:pk>/", RoutineDetailView.as_view(), name="bodiez-routine"),
    path("routines/<int:pk>/exercises/", RoutineExercisesView.as_view(),
         name="bodiez-routine-exercises"),
    path("sessions/", SessionsView.as_view(), name="bodiez-sessions"),
    path("sessions/<int:pk>/sets/", SessionSetsView.as_view(), name="bodiez-session-sets"),
    path("sessions/<int:pk>/finish/", SessionFinishView.as_view(), name="bodiez-session-finish"),
    path("progress/", ProgressView.as_view(), name="bodiez-progress"),
    path("bodymap/", BodyMapView.as_view(), name="bodiez-bodymap"),
    path("coach/", CoachView.as_view(), name="bodiez-coach"),
    path("items/", ItemsView.as_view(), name="bodiez-items"),
    path("items/<int:pk>/", ItemDetailView.as_view(), name="bodiez-item"),
    path("metrics/", MetricsView.as_view(), name="bodiez-metrics"),
    path("goals/", GoalsView.as_view(), name="bodiez-goals"),
    path("locations/", LocationsView.as_view(), name="bodiez-locations"),
    path("locations/<int:pk>/", LocationDetailView.as_view(), name="bodiez-location"),
]
