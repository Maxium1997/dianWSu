from django.urls import path

from . import views


app_name = 'rental'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('properties/', views.property_list, name='property_list'),
    path('properties/new/', views.property_create, name='property_create'),
    path('properties/<int:property_id>/', views.property_detail, name='property_detail'),
    path('properties/<int:property_id>/edit/', views.property_edit, name='property_edit'),
    path('properties/<int:property_id>/units/new/', views.unit_create, name='unit_create'),
    path('units/<int:unit_id>/edit/', views.unit_edit, name='unit_edit'),
    path('units/<int:unit_id>/leases/new/', views.lease_create, name='lease_create'),
    path('bills/', views.bill_list, name='bill_list'),
    path('bills/<int:bill_id>/', views.bill_detail, name='bill_detail'),
    path('bills/<int:bill_id>/submit/', views.bill_submit, name='bill_submit'),
    path('bills/<int:bill_id>/confirm/', views.bill_confirm, name='bill_confirm'),
    path('bills/<int:bill_id>/payment/', views.bill_payment, name='bill_payment'),
    path('bills/<int:bill_id>/payment/confirm/', views.bill_payment_confirm, name='bill_payment_confirm'),
    path('invitations/<uuid:token>/', views.invitation_accept, name='invitation_accept'),
    path('invitations/', views.invitation_list, name='invitation_list'),
    path('invitations/new/', views.invitation_create, name='invitation_create'),
    path('maintenance/', views.maintenance_list, name='maintenance_list'),
    path('maintenance/new/', views.maintenance_create, name='maintenance_create'),
    path('announcements/', views.announcement_list, name='announcement_list'),
    path('files/<path:stored_name>/', views.rental_file, name='rental_file'),
]
