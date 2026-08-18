from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model, authenticate, login, logout
from django.contrib import messages

User = get_user_model()


def register_view(request):
    if request.method == 'POST':
        full_name = request.POST.get('fullName', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm = request.POST.get('confirmPassword', '')
        institution = request.POST.get('institution', '').strip()
        user_type = request.POST.get('userType', 'other')
        newsletter = 'newsletter' in request.POST

        # Validation
        if not full_name:
            messages.error(request, 'Full name is required')
            return redirect('register')

        if not email:
            messages.error(request, 'Email is required')
            return redirect('register')

        if len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters')
            return redirect('register')

        if password != confirm:
            messages.error(request, 'Passwords do not match')
            return redirect('register')

        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already registered')
            return redirect('register')

        try:
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                full_name=full_name,
                institution=institution,
                user_type=user_type,
                newsletter=newsletter,
            )
            messages.success(request, 'Account created successfully! You can now log in.')
            return redirect('login')
        except Exception as e:
            messages.error(request, f'Error creating account: {e}')
            return redirect('register')

    return render(request, 'register.html')


def login_view(request):
    if request.method == "POST":
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        remember_me = request.POST.get('rememberMe')

        user = authenticate(request, username=email, password=password)
        if user is not None:
            login(request, user)

            # Handle "Remember Me"
            if remember_me:
                # Keep session for 30 days
                request.session.set_expiry(60 * 60 * 24 * 30)
            else:
                # Session expires when browser closes
                request.session.set_expiry(0)

            return redirect('web_dashboard:dashboard')
        else:
            messages.error(request, "Invalid email or password")
            return render(request, "login.html")

    return render(request, "login.html")


def logout_view(request):
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect('login')
