from django.db import models
from django.conf import settings


class UserPreferences(models.Model):
    """Stores per-user display & notification preferences."""

    MAP_LAYER_CHOICES = (
        ('satellite', 'Satellite View'),
        ('street', 'Street Map'),
    )

    EXPORT_FORMAT_CHOICES = (
        ('pdf', 'PDF'),
        ('png', 'PNG'),
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='preferences',
    )

    # Display preferences
    default_map_layer = models.CharField(max_length=20, choices=MAP_LAYER_CHOICES, default='satellite')
    default_season = models.CharField(max_length=20, default='spring')
    show_temperature_chart = models.BooleanField(default=True)
    show_advanced_metrics = models.BooleanField(default=True)

    # Notification preferences
    notify_analysis_complete = models.BooleanField(default=True)
    notify_weekly_digest = models.BooleanField(default=False)

    # Export settings
    export_format = models.CharField(max_length=10, choices=EXPORT_FORMAT_CHOICES, default='pdf')
    include_map_in_report = models.BooleanField(default=True)
    include_charts_in_report = models.BooleanField(default=True)

    def __str__(self):
        return f"Preferences for {self.user}"


class AnalysisHistory(models.Model):
    """Stores a record of each analysis a user runs."""

    ANALYSIS_TYPE_CHOICES = (
        ('current', 'Current'),
        ('temporal', 'Temporal'),
        ('upload', 'Custom Upload'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='analysis_history',
    )
    result_id = models.CharField(max_length=255, unique=True)
    title = models.CharField(max_length=300, blank=True)
    analysis_type = models.CharField(
        max_length=20, choices=ANALYSIS_TYPE_CHOICES, default='current'
    )
    coordinates = models.JSONField(null=True, blank=True)
    summary = models.TextField(blank=True, default='', help_text='Short summary of the analysis result')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Analysis histories'

    def __str__(self):
        return f"{self.title or self.result_id} — {self.user}"
