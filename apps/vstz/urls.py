from django.urls import path

from .views import CatalogView, RackView, ScanView, SearchView

urlpatterns = [
    path("catalog/", CatalogView.as_view(), name="vstz-catalog"),
    path("rack/", RackView.as_view(), name="vstz-rack"),
    path("rack/scan/", ScanView.as_view(), name="vstz-scan"),
    path("search/", SearchView.as_view(), name="vstz-search"),
]
