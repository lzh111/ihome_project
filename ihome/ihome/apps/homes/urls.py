from django.conf.urls import url
from homes import views
urlpatterns = [
    url(r'^areas$', views.AreaView.as_view()),
    url(r'^houses$', views.HouseView.as_view()),
    url(r'^user/houses$', views.UserHouseView.as_view()),
    url(r'^houses/(?P<house_id>\d+)/images$', views.HouseImageView.as_view()),
    url(r'^houses/index$', views.HouseIndexView.as_view()),
    url(r'^houses/(?P<house_id>\d+)$', views.HouseDetailView.as_view()),
]