from django.contrib import admin
from .models import AnalysisHistory


@admin.register(AnalysisHistory)
class AnalysisHistoryAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'analysis_type', 'created_at')
    list_filter = ('analysis_type', 'created_at')
    search_fields = ('title', 'result_id', 'user__email')
    readonly_fields = ('result_id', 'created_at')
