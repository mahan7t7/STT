# core/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing, name='landing'),


    path('signup/', views.signup, name='signup'),


    path('dashboard/', views.dashboard, name='dashboard'),


    path('upload/', views.upload_file, name='upload_file'),

 
    path('get-files/', views.get_files, name='get_files'),
    path("update-row/<int:file_id>/", views.update_row, name="update_row"),


    path('delete/<int:pk>/', views.delete_file, name='delete_file'),


    path('download/txt/<int:file_id>/', views.download_txt, name='download_txt'),
    path('download/word/<int:file_id>/', views.download_word, name='download_word'),
    path('download/pdf/<int:file_id>/', views.download_pdf, name='download_pdf'),
    
    
     path("import/create/", views.create_import_batch, name="create_import_batch"),
    path("import/status/<int:batch_id>/", views.import_batch_status, name="import_batch_status"),
    path("import/enqueue/", views.enqueue_import_items, name="enqueue_import_items"),
]
