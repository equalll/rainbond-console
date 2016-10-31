from django.conf.urls import patterns, url
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from admin.views.adminview import *

urlpatterns = patterns(
    '',
    url(r'^/?$', login_required(AdminViews.as_view())),
)
