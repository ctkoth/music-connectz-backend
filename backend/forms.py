from django import forms
from .models import Work

class WorkForm(forms.ModelForm):
    class Meta:
        model = Work
        fields = ['title', 'file', 'date_created', 'price', 'genre', 'thumbnail', 'skills']
        widgets = {
            'date_created': forms.DateInput(attrs={'type': 'date'}),
            'skills': forms.CheckboxSelectMultiple,
        }
