
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .forms import WorkForm
from .models import Work

def home(request):
    return render(request, "home.html")


@login_required
def upload_work(request):
    if request.method == 'POST':
        form = WorkForm(request.POST, request.FILES)
        if form.is_valid():
            work = form.save(commit=False)
            work.uploaded_by = request.user
            work.save()
            return redirect('home')
    else:
        form = WorkForm()
    return render(request, 'upload_work.html', {'form': form})
