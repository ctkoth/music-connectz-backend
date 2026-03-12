from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .serializers import RegisterSerializer

# API endpoint for user registration
@api_view(['POST'])
@permission_classes([AllowAny])
def api_register(request):
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({"success": "User registered successfully."}, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
from django.http import JsonResponse
def google_available(request):
    return JsonResponse({"available": True})

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
