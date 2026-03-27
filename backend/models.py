from django.db import models
from django.contrib.auth.models import User

class Skill(models.Model):
    name = models.CharField(max_length=100)
    def __str__(self):
        return self.name

class Persona(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    skills = models.ManyToManyField(Skill, blank=True)
    def __str__(self):
        return f"{self.name} ({self.user.username})"

class Work(models.Model):
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='uploads/')
    date_created = models.DateField()
    date_uploaded = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE)
    price = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    genre = models.CharField(max_length=100, blank=True)
    thumbnail = models.ImageField(upload_to='thumbnails/', blank=True, null=True)
    skills = models.ManyToManyField(Skill, blank=True)

    def __str__(self):
        return self.title


class SiteAnalytics(models.Model):
    key = models.CharField(max_length=32, unique=True, default='global')
    total_visits = models.PositiveIntegerField(default=0)
    unique_visitors = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.key}: {self.total_visits} visits"


class VisitorRecord(models.Model):
    visitor_key = models.CharField(max_length=128, unique=True)
    visit_count = models.PositiveIntegerField(default=1)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.visitor_key
