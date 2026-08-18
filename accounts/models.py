from django.contrib.auth.models import AbstractUser
from django.db import models

class CustomUser(AbstractUser):

    USER_TYPE_CHOICES = (
        ('student', 'Student'),
        ('researcher', 'Researcher'),
        ('urban_planner', 'Urban Planner'),
        ('government', 'Government Official'),
        ('ngo', 'NGO Worker'),
        ('other', 'Other'),
    )

    full_name = models.CharField(max_length=150)
    institution = models.CharField(max_length=255, blank=True)
    user_type = models.CharField(max_length=30, choices=USER_TYPE_CHOICES)
    newsletter = models.BooleanField(default=True)

    def __str__(self):
        return self.email
