from django.shortcuts import render, redirect,get_object_or_404
from .models import Cart,Product,UserProfile,Brand,Order,OrderItem
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.hashers import make_password,check_password
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from functools import wraps
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

def admin_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # ✅ If user is logged in as Django superuser
        if request.user.is_authenticated and request.user.is_superuser:
            return view_func(request, *args, **kwargs)

        # ✅ If logged in custom user and NOT admin — deny access
        user_id = request.session.get('user_id')
        if user_id:
            user = UserProfile.objects.filter(id=user_id).first()
            if user and getattr(user, 'is_admin', False):
                return view_func(request, *args, **kwargs)

        # 🚫 Unauthorized access
        messages.error(request, "You are not authorized to access this page.")
        return redirect('signin')
    return wrapper

def user_login_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.session.get('user_id'):
            messages.warning(request, "Please sign in to continue.")
            return redirect('signin')
        return view_func(request, *args, **kwargs)
    return wrapper

# Create your views here.
def landing(request):
    return render(request, 'landing.html')
def signup(request):
    return render(request, 'signup.html')

def signup_fun(request):
    if request.method == 'POST':
        fname = request.POST.get('fname').strip()
        lname = request.POST.get('lname')
        username = request.POST.get('uname')
        address = request.POST.get('address')
        age = request.POST.get('age')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        password = request.POST.get('password')
        confirmpw = request.POST.get('cpassword')
        image = request.FILES.get('image')

        # ---------- VALIDATION SECTION ----------

        # Password validation
        if len(password) < 6:
            messages.error(request, "Password must be at least 8 characters long!")
            return redirect('signup')

        if password != confirmpw:
            messages.error(request, "Passwords do not match!")
            return redirect('signup')

        # Duplicate checks
        if UserProfile.objects.filter(username=username).exists():
            messages.error(request, "Username already exists!")
            return redirect('signup')

        if UserProfile.objects.filter(email=email).exists():
            messages.error(request, "Email already registered!")
            return redirect('signup')

        if UserProfile.objects.filter(phno=phone).exists():
            messages.error(request, "Phone number already registered!")
            return redirect('signup')

        # Email format validation
        if not email.endswith('.com'):
            messages.error(request, "Email must end with '.com' extension!")
            return redirect('signup')

        # Phone validation
        if not (phone.isdigit() and len(phone) == 10):
            messages.error(request, "Phone number must contain exactly 10 digits!")
            return redirect('signup')

        # ---------- USER CREATION ----------
        user = UserProfile(
            fname=fname,
            lname=lname,
            address=address,
            phno=phone,
            username=username,
            email=email,
            password=make_password(password),  # (In production, use make_password)
            image=image
        )
        user.save()

        # ---------- EMAIL CONFIRMATION ----------
        subject = "Welcome to EchoPods!"
        message = f"Hello {fname},\n\nYour registration was successful!\nYou can now log in and start exploring our products.\n\n— EchoPods Team —"
        try:
            send_mail(subject, message, settings.EMAIL_HOST_USER, [email])
        except Exception as e:
            print(f"Email send failed: {e}")  # optional debug log

        # ---------- SUCCESS MESSAGE ----------
        messages.success(request, "Registration successful! Welcome to EchoPods 🎧")
        return redirect('signin')

    return render(request, 'signup.html')


def signin(request):
    return render(request, 'signin.html')


def login_fun(request):
    if request.method == 'POST':
        uname = request.POST.get('username')
        password = request.POST.get('password')
        
        # 🔹 1. First, check if this is a Django superuser (admin login)
        admin_user = authenticate(username=uname, password=password)
        if admin_user is not None and admin_user.is_superuser:
            login(request, admin_user)
            messages.success(request, f"Welcome, {admin_user.username} (Admin) 👑")
            return redirect('admin_home')

        # 🔹 2. Otherwise, check custom UserProfile model
        user = UserProfile.objects.filter(username=uname).first() or UserProfile.objects.filter(email=uname).first()

        if user:
            # Check if password matches
            if check_password(password, user.password):
                # Check if admin approved the user
                if user.status == '0':  # Pending approval
                    messages.warning(request, "Your account is awaiting admin approval. Please try again later.")
                    return redirect('signin')

                elif user.status == '2':  # Disapproved
                    messages.error(request, "Your account has been disapproved. Contact support for help.")
                    return redirect('signin')

                elif user.status == '1':  # Approved ✅
                    request.session['user_id'] = user.id
                    request.session['username'] = user.username
                    messages.success(request, f"Welcome back, {user.fname} 👋")
                    return redirect('user_home')

            # Wrong password
            messages.error(request, "Invalid password. Please try again.")
            return redirect('signin')

        else:
            messages.error(request, "User not found. Please check your credentials.")
            return redirect('signin')

    return render(request, 'signin.html')

@admin_required
def admin_home(request):
    # Fetch all brands (your existing functionality)
    brands = Brand.objects.all()

    # Count users waiting for approval
    pending_count = UserProfile.objects.filter(status='0', is_admin=False).count()

    # Pass both to the template
    return render(request, 'admin_home.html', {
        'brands': brands,
        'pending_count': pending_count
    })

@user_login_required
def user_home(request):
    user = get_object_or_404(UserProfile, id=request.session.get('user_id'))

    # Restrict if user is not approved
    if user.status != '1':
        messages.warning(request, "Access denied. Your account is not approved yet.")
        return redirect('signin')

    brands = Brand.objects.all()
    return render(request, 'user_home.html', {'user': user, 'brands': brands})


def logout_fun(request):
    request.session.flush()
    messages.success(request, "You’ve been logged out successfully.")
    return redirect('signin')

@admin_required
def add_brand(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        image = request.FILES.get('image')

        # --- Validation ---
        if not name:
            messages.error(request, "Brand name cannot be empty!")
            return redirect('add_brand')

        # Check for duplicate (case-insensitive)
        if Brand.objects.filter(name__iexact=name).exists():
            messages.error(request, f"Brand '{name}' already exists!")
            return redirect('add_brand')

        # --- Save Brand ---
        Brand.objects.create(name=name, image=image)
        messages.success(request, f"Brand '{name}' added successfully!")
        return redirect('show_brands')

    return render(request, 'add_brand.html')
@admin_required
def edit_brand(request, id):
    brand = get_object_or_404(Brand, id=id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()

        # --- Validation ---
        if not name:
            messages.error(request, "Brand name cannot be empty!")
            return redirect('edit_brand', id=id)

        # Check if another brand already has this name
        if Brand.objects.filter(name__iexact=name).exclude(id=brand.id).exists():
            messages.error(request, f"Brand '{name}' already exists!")
            return redirect('edit_brand', id=id)

        brand.name = name

        if 'image' in request.FILES and request.FILES['image']:
            brand.image = request.FILES['image']

        brand.save()
        messages.success(request, "Brand updated successfully!")
        return redirect('show_brands')

    return render(request, 'edit_brand.html', {'brand': brand})
@admin_required
def add_product(request):
    brands = Brand.objects.all()

    if request.method == 'POST':
        brand_id = request.POST.get('brand')
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description')
        price = request.POST.get('price')
        stock = request.POST.get('stock')
        image = request.FILES.get('image')

        # --- Validation ---
        if not brand_id:
            messages.error(request, "Please select a brand.")
            return redirect('add_product')

        if not name:
            messages.error(request, "Product name cannot be empty!")
            return redirect('add_product')

        brand = get_object_or_404(Brand, id=brand_id)

        # Check duplicate name under same brand
        if Product.objects.filter(name__iexact=name, brand=brand).exists():
            messages.error(request, f"Product '{name}' already exists under brand '{brand.name}'!")
            return redirect('add_product')

        # --- Save Product ---
        Product.objects.create(
            brand=brand,
            name=name,
            description=description,
            price=price,
            stock=stock,
            image=image
        )

        messages.success(request, f"Product '{name}' added successfully!")
        return redirect('show_products')

    return render(request, 'add_product.html', {'brands': brands})

def delete_brand(request, id):
    brand = get_object_or_404(Brand, id=id)
    brand.delete()
    messages.success(request, "Brand deleted successfully!")
    return redirect('show_brands')

@admin_required
def show_products(request):
    products  = Product.objects.all()
    return render(request, 'show_products.html',{'products': products} )
@admin_required
def show_brands(request):
    brands= Brand.objects.all()
    return render(request, 'show_brands.html',{'brands': brands} )
@admin_required
def edit_product(request, id):
    product = get_object_or_404(Product, id=id)
    brands = Brand.objects.all()

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description')
        price = request.POST.get('price')
        stock = request.POST.get('stock')
        brand_id = request.POST.get('brand')

        if not name:
            messages.error(request, "Product name cannot be empty!")
            return redirect('edit_product', id=id)

        if brand_id:
            brand = get_object_or_404(Brand, id=brand_id)
            product.brand = brand

        # Check duplicate product under same brand
        if Product.objects.filter(name__iexact=name, brand=product.brand).exclude(id=product.id).exists():
            messages.error(request, f"Product '{name}' already exists under brand '{product.brand.name}'!")
            return redirect('edit_product', id=id)

        # Update fields
        product.name = name
        product.description = description
        product.price = price
        product.stock = stock

        if 'image' in request.FILES and request.FILES['image']:
            product.image = request.FILES['image']

        product.save()
        messages.success(request, "Product updated successfully!")
        return redirect('show_products')

    return render(request, 'edit_product.html', {'product': product, 'brands': brands})

def delete_product(request, id):
    product = get_object_or_404(Product, id=id)
    product.delete()
    messages.success(request, "Product deleted successfully!")
    return redirect('show_products')
@admin_required
def approval_page(request):
    # Show all non-admin users (pending/approved/disapproved)
    users = UserProfile.objects.filter(is_admin=False)
    return render(request, 'approval_page.html', {'users': users})

def approve_user(request, id):
    user = get_object_or_404(UserProfile, id=id)

    if user.status != '1':
        user.status = '1'
        user.save()

        # Send approval notification email (no password shared)
        subject = "Your EchoPods Account Has Been Approved 🎉"
        message = (
            f"Hi {user.username},\n\n"
            "Good news! Your account has been approved by the EchoPods Admin Team.\n\n"
            "You can now log in using your registered credentials and start exploring our platform.\n\n"
            "Thank you for joining EchoPods!\n\n"
            "Best regards,\n"
            "EchoPods Team"
        )

        send_mail(subject, message, settings.EMAIL_HOST_USER, [user.email])

        messages.success(request, f"User '{user.username}' approved successfully and notified via email.")
    else:
        messages.info(request, f"User '{user.username}' is already approved.")

    return redirect('approval_page')


def disapprove_user(request, id):
    user = get_object_or_404(UserProfile, id=id)
    user.status = '2'
    user.save()
    messages.warning(request, f"User '{user.username}' disapproved.")
    return redirect('approval_page')

def view_users(request):
    """Display all non-admin users."""
    users = UserProfile.objects.filter(is_admin=False)
    return render(request, 'view_users.html', {'users': users})

def delete_user(request, id):
    """Delete a user by ID."""
    user = get_object_or_404(UserProfile, id=id)
    username = user.username
    user.delete()
    messages.success(request, f"User '{username}' deleted successfully!")
    return redirect('view_users')

@user_login_required
def brand_products(request, brand_id):
    brand = get_object_or_404(Brand, id=brand_id)
    products = Product.objects.filter(brand=brand)

    # Pass user for profile image display
    user = None
    if request.session.get('user_id'):
        user = get_object_or_404(UserProfile, id=request.session['user_id'])

    return render(request, 'brand_products.html', {
        'brand': brand,
        'products': products,
        'user': user,
        'brands': Brand.objects.all(),  # So navbar still works dynamically
    })
@user_login_required
def add_to_cart(request, product_id):
    if not request.session.get('user_id'):
        messages.error(request, "Please log in to add items to your cart.")
        return redirect('signin')

    user = get_object_or_404(UserProfile, id=request.session['user_id'])
    product = get_object_or_404(Product, id=product_id)

    quantity = int(request.POST.get('quantity', 1))

    # Check if enough stock is available
    if product.stock < quantity:
        messages.error(request, f"Only {product.stock} unit(s) of '{product.name}' available.")
        return redirect('brand_products', brand_id=product.brand.id)

    # Get or create the cart item
    cart_item, created = Cart.objects.get_or_create(user=user, product=product)
    if not created:
        # Adding more to existing cart item
        if product.stock < (cart_item.quantity + quantity):
            messages.warning(request, f"Cannot add more — only {product.stock} left in stock.")
            return redirect('brand_products', brand_id=product.brand.id)
        cart_item.quantity += quantity
        messages.info(request, f"Updated quantity of '{product.name}' in your cart.")
    else:
        cart_item.quantity = quantity
        messages.success(request, f"'{product.name}' added to your cart!")

    cart_item.save()

    # Reduce stock
    product.stock -= quantity
    product.save()

    return redirect('view_cart')

@user_login_required
def view_cart(request):
    if not request.session.get('user_id'):
        return redirect('signin')

    user = get_object_or_404(UserProfile, id=request.session['user_id'])
    cart_items = Cart.objects.filter(user=user)
    total_price = sum(item.total_price for item in cart_items)
    cart_count = cart_items.count()  # ✅ Add this for navbar badge

    if request.method == "POST":
        for item in cart_items:
            new_qty = int(request.POST.get(f'quantity_{item.id}', item.quantity))

            # Restore stock difference
            if new_qty < item.quantity:
                product = item.product
                product.stock += (item.quantity - new_qty)
                product.save()
            elif new_qty > item.quantity:
                product = item.product
                if product.stock < (new_qty - item.quantity):
                    messages.error(request, f"Not enough stock for '{product.name}'.")
                    continue
                product.stock -= (new_qty - item.quantity)
                product.save()

            if new_qty <= 0:
                # Restore stock if removed
                item.product.stock += item.quantity
                item.product.save()
                item.delete()
            else:
                item.quantity = new_qty
                item.save()

        messages.success(request, "Cart updated successfully!")
        return redirect('view_cart')

    return render(request, 'view_cart.html', {
        'user': user,            # ✅ Add this line
        'brands': Brand.objects.all(),  # ✅ For dropdown
        'cart_items': cart_items,
        'total_price': total_price,
        'cart_count': cart_count, # ✅ Badge count
    })


def remove_cart_item(request, item_id):
    item = get_object_or_404(Cart,id=item_id)
    item.delete()
    messages.info(request, f"Removed '{item.product.name}' from your cart.")
    return redirect('view_cart')

@user_login_required
def edit_profile(request, id):
    user = get_object_or_404(UserProfile, id=id)

    # 🔒 Prevent editing others' profiles
    if request.session.get('user_id') != user.id:
        messages.error(request, "Unauthorized access.")
        return redirect('user_home')

    if request.method == 'POST':
        fname = request.POST.get('fname', '').strip()
        lname = request.POST.get('lname', '').strip()
        address = request.POST.get('address', '').strip()
        username = request.POST.get('uname', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        image = request.FILES.get('image')

        # ========== VALIDATION SECTION ==========

        # 1️⃣ Required field check
        if not all([fname, lname, address, username, email, phone]):
            messages.error(request, "All fields are required.")
            return redirect('edit_profile', id=user.id)

        # 2️⃣ Username validation
        if len(username) < 3:
            messages.error(request, "Username must be at least 3 characters long.")
            return redirect('edit_profile', id=user.id)

        if " " in username:
            messages.error(request, "Username cannot contain spaces.")
            return redirect('edit_profile', id=user.id)

        # 🚫 Check for existing username (excluding current user)
        if UserProfile.objects.filter(username=username).exclude(id=user.id).exists():
            messages.error(request, f"The username '{username}' is already taken. Please choose another.")
            return redirect('edit_profile', id=user.id)

        # 3️⃣ Email validation
        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, "Enter a valid email address (must include .com).")
            return redirect('edit_profile', id=user.id)

        if not email.endswith('.com'):
            messages.error(request, "Email must end with '.com'.")
            return redirect('edit_profile', id=user.id)

        # 🚫 Check if email already exists (excluding current user)
        if UserProfile.objects.filter(email=email).exclude(id=user.id).exists():
            messages.error(request, "This email is already registered with another account.")
            return redirect('edit_profile', id=user.id)

        # 4️⃣ Phone validation
        if not (phone.isdigit() and len(phone) == 10):
            messages.error(request, "Phone number must contain exactly 10 digits.")
            return redirect('edit_profile', id=user.id)

        if UserProfile.objects.filter(phno=phone).exclude(id=user.id).exists():
            messages.error(request, "This phone number is already in use.")
            return redirect('edit_profile', id=user.id)

        # ========== SAVE UPDATED DATA ==========
        user.fname = fname
        user.lname = lname
        user.address = address
        user.username = username
        user.email = email
        user.phno = phone

        if image:
            user.image = image

        user.save()

        messages.success(request, "Profile updated successfully! ✅")
        return redirect('user_home')

    # For GET request — show form with existing user data
    return render(request, 'edit_profile.html', {
        'user': user,
        'brands': Brand.objects.all(),
        'cart_count': Cart.objects.filter(user=user).count(),
    })

from django.db import transaction

@user_login_required
@transaction.atomic
def checkout_order(request):
    if not request.session.get('user_id'):
        return redirect('signin')

    user = get_object_or_404(UserProfile, id=request.session['user_id'])

    if request.method == "POST":
        selected_ids = request.POST.getlist('selected_items')

        if not selected_ids:
            messages.warning(request, "No items selected for checkout!")
            return redirect('view_cart')

        cart_items = Cart.objects.filter(user=user, id__in=selected_ids)
        if not cart_items.exists():
            messages.warning(request, "Selected items not found!")
            return redirect('view_cart')

        total_price = sum(item.total_price for item in cart_items)

        order = Order.objects.create(user=user, total_amount=total_price, status='Pending')

        for item in cart_items:
            OrderItem.objects.create(
                order=order,
                product=item.product,
                quantity=item.quantity,
                price=item.product.price
            )
            item.product.stock -= item.quantity
            item.product.save()

        cart_items.delete()
        messages.success(request, "Selected items have been ordered successfully!")
        return redirect('my_orders')

    return redirect('view_cart')



def my_orders(request):
    if not request.session.get('user_id'):
        return redirect('signin')

    user = get_object_or_404(UserProfile, id=request.session['user_id'])
    orders = (
        Order.objects.filter(user=user)
        .prefetch_related('items__product')  # ✅ use related_name 'items'
        .order_by('-created_at')
    )

    return render(request, 'my_orders.html', {
        'user': user,
        'orders': orders,
        'brands': Brand.objects.all(),
        'cart_count': Cart.objects.filter(user=user).count(),
    })

from django.http import JsonResponse

def update_cart_quantity(request):
    if request.method == "POST":
        cart_id = request.POST.get('cart_id')
        new_qty = int(request.POST.get('quantity'))

        cart_item = get_object_or_404(Cart, id=cart_id)
        product = cart_item.product

        # Handle quantity 0 → remove item
        if new_qty <= 0:
            product.stock += cart_item.quantity  # Restore stock
            product.save()
            cart_item.delete()
            return JsonResponse({'removed': True})

        # Handle stock limits
        if new_qty > product.stock:
            return JsonResponse({'error': f"Only {product.stock} items available."})

        # Adjust stock
        stock_diff = new_qty - cart_item.quantity
        product.stock -= stock_diff
        product.save()

        # Update cart quantity
        cart_item.quantity = new_qty
        cart_item.save()

        # Calculate updated totals
        total_price = sum(item.total_price for item in Cart.objects.filter(user=cart_item.user))
        item_total = cart_item.product.price * cart_item.quantity

        return JsonResponse({
            'removed': False,
            'item_total': item_total,
            'total_price': total_price
        })

    return JsonResponse({'error': 'Invalid request'}, status=400)
def cancel_order_item(request, item_id):
    item = get_object_or_404(OrderItem, id=item_id)

    # Only allow cancelling if status is still Pending
    if item.order.status != 'Pending':
        messages.error(request, "You can only cancel pending orders.")
        return redirect('my_orders')

    # Restore stock to product
    product = item.product
    product.stock += item.quantity
    product.save()

    # Delete item from order
    item.delete()

    # If all items removed, mark order as cancelled
    if not item.order.items.exists():
        item.order.status = 'Cancelled'
        item.order.save()

    messages.success(request, "Order item cancelled successfully.")
    return redirect('my_orders')