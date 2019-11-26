from django.conf.urls import url
from order import views
urlpatterns = [
    url(r'^orders$', views.OrdersView.as_view()),
    url(r'^orders/(?P<order_id>\d+)/status$', views.OrdersStatusView.as_view()),
    url(r'^orders/(?P<order_id>\d+)/comment$', views.OrdersCommentView.as_view()),
]