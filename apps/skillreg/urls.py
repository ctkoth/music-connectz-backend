from django.urls import path

from . import views as v

urlpatterns = [
    path("catalog/", v.CatalogView.as_view()),
    path("mine/", v.MySkillsView.as_view()),
    path("choices/", v.ChoicesView.as_view()),
    path("profile/<str:username>/", v.PublicProfileView.as_view()),
    path("tag-work/", v.TagWorkView.as_view()),
    path("rate/", v.RateView.as_view()),
    path("gates/<str:post_type>/<int:post_id>/", v.GateView.as_view()),
    path("gates/<str:post_type>/<int:post_id>/check/", v.GateCheckView.as_view()),
    path("search/", v.SearchView.as_view()),
    path("posts/", v.BrowsePostsView.as_view()),
    path("works/", v.SearchWorksView.as_view()),
    path("split/<str:work_type>/<int:work_id>/", v.SplitPreviewView.as_view()),
]
