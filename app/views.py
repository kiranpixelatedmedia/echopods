import uuid
import logging
from functools import wraps

logger = logging.getLogger(__name__)

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.hashers import check_password, make_password
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from app.supabase_client import supabase 

from .models import (
    Brand, Cart, Category, Coupon, Order, OrderItem,
    Product, ProductReview, ProductVariant, UserProfile,
)


# ======================================================
# HELPERS
# ======================================================

TAX_RATE = getattr(settings, 'TAX_RATE', 0.05)
SHIPPING_THRESHOLD = 500
SHIPPING_COST = 10.00


def _get_logged_in_user(request):
    """Returns the UserProfile for the currently logged-in session user, or None."""
    user_id = request.session.get('user_id')
    if user_id:
        return UserProfile.objects.filter(id=user_id).first()
    return None


def _calculate_totals(cart_items):
    """Returns (subtotal, tax, shipping, grand_total) as floats."""
    subtotal = float(sum(item.total_price for item in cart_items))
    tax = round(subtotal * TAX_RATE, 2)
    shipping = 0.00 if subtotal >= SHIPPING_THRESHOLD else SHIPPING_COST
    grand_total = round(subtotal + tax + shipping, 2)
    return subtotal, tax, shipping, grand_total


def _handle_image_upload(request, image_file, bucket_name='media'):
    """
    Validates file size and uploads to Supabase Storage if available.
    Returns the public URL or the file object itself if cloud upload fails.
    """
    if not image_file:
        return None

    # 1. Validate Size
    max_size = getattr(settings, 'MAX_UPLOAD_SIZE', 4 * 1024 * 1024)
    if image_file.size > max_size:
        messages.error(request, f"File too large. Maximum size is {max_size // (1024*1024)}MB.")
        return "TOO_LARGE"

    # 2. Try Supabase Storage
    if supabase:
        try:
            file_name = f"{uuid.uuid4()}_{image_file.name}"
            # Convert file to bytes
            file_data = image_file.read()
            
            # Reset file pointer for potential fallback
            image_file.seek(0)
            
            res = supabase.storage.from_(bucket_name).upload(
                path=file_name,
                file=file_data,
                file_options={"content-type": image_file.content_type}
            )
            # Get public URL
            public_url = supabase.storage.from_(bucket_name).get_public_url(file_name)
            return public_url
        except Exception as e:
            logger.error(f"Supabase Storage Upload failed: {e}")
            # Fallback to local only if in DEBUG mode
            if not settings.DEBUG:
                messages.warning(request, "Image upload failed. Profile created without image.")
                return None
            return image_file
    
    if not settings.DEBUG:
        # On Vercel, we can't save locally. If no supabase, we must return None.
        messages.warning(request, "Cloud storage not configured. Profile created without image.")
        return None
    return image_file


# ======================================================
# DECORATORS
# ======================================================

def admin_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        user = _get_logged_in_user(request)
        if user and getattr(user, 'is_admin', False):
            return view_func(request, *args, **kwargs)
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


# ======================================================
# PUBLIC & AUTH VIEWS
# ======================================================

def landing(request):
    return render(request, 'landing.html')


def signup(request):
    if request.method == 'POST':
        fname    = request.POST.get('fname', '').strip()
        lname    = request.POST.get('lname', '').strip()
        username = request.POST.get('uname', '').strip()
        address  = request.POST.get('address', '').strip()
        email    = request.POST.get('email', '').strip()
        phone    = request.POST.get('phone', '').strip()
        password = request.POST.get('password', '')
        confirm  = request.POST.get('cpassword', '')
        image_file = request.FILES.get('image')

        if len(password) < 6 or password != confirm:
            messages.error(request, "Passwords must match and be at least 6 characters.")
            return redirect('signup')

        # Handle Cloud Upload
        image_result = _handle_image_upload(request, image_file)
        if image_result == "TOO_LARGE":
            return redirect('signup')

        if UserProfile.objects.filter(username=username).exists():
            messages.error(request, "Username already taken.")
            return redirect('signup')

        if UserProfile.objects.filter(email=email).exists():
            messages.error(request, "Email already registered.")
            return redirect('signup')

        UserProfile.objects.create(
            fname=fname, lname=lname, address=address, phno=phone,
            username=username, email=email,
            password=make_password(password),
            image=image_result, status='1',
        )
        messages.success(request, "Registration successful! Welcome to EchoPods 🎧")
        return redirect('signin')

    return render(request, 'signup.html')


def signin(request):
    if request.method == 'POST':
        uname    = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        # Django admin check
        admin_user = authenticate(username=uname, password=password)
        if admin_user and admin_user.is_superuser:
            login(request, admin_user)
            return redirect('admin_home')

        # Custom user lookup (username OR email)
        user = (
            UserProfile.objects.filter(username=uname).first() or
            UserProfile.objects.filter(email=uname).first()
        )

        if not user:
            messages.error(request, "No account found with that username or email.")
            return redirect('signin')

        if not check_password(password, user.password):
            user.failed_login_attempts += 1
            user.save(update_fields=['failed_login_attempts'])
            messages.error(request, "Incorrect password.")
            return redirect('signin')

        if user.status == '0':
            messages.warning(request, "Your account has been disabled.")
            return redirect('signin')

        request.session['user_id'] = user.id
        request.session['username'] = user.username
        messages.success(request, f"Welcome back, {user.fname} 👋")
        return redirect('admin_home' if user.is_admin else 'user_home')

    return render(request, 'signin.html')


def logout_fun(request):
    request.session.flush()
    messages.success(request, "You've been logged out.")
    return redirect('signin')


@user_login_required
def edit_profile(request, id):
    user = get_object_or_404(UserProfile, id=id)
    # Prevent editing another user's profile
    if request.session.get('user_id') != user.id:
        return redirect('user_home')

    if request.method == 'POST':
        user.fname   = request.POST.get('fname', '').strip()
        user.lname   = request.POST.get('lname', '').strip()
        user.address = request.POST.get('address', '').strip()
        user.phno    = request.POST.get('phone', '').strip()
        
        image_file = request.FILES.get('image')
        if image_file:
            image_result = _handle_image_upload(request, image_file)
            if image_result == "TOO_LARGE":
                return redirect('edit_profile', id=user.id)
            user.image = image_result
            
        user.save()
        messages.success(request, "Profile updated successfully! ✅")
        return redirect('user_home')

    return render(request, 'edit_profile.html', {'user': user})


# ======================================================
# ADMIN VIEWS
# ======================================================

@admin_required
def admin_home(request):
    revenue = (
        Order.objects.filter(status__in=['Shipped', 'Delivered'])
        .aggregate(total=Sum('grand_total'))['total'] or 0
    )
    return render(request, 'admin_home.html', {
        'total_users':   UserProfile.objects.filter(is_admin=False).count(),
        'revenue':       revenue,
        'low_stock':     Product.objects.filter(stock__lte=5).count(),
        'recent_orders': Order.objects.order_by('-created_at')[:5],
        'brands':        Brand.objects.all(),
        'pending_count': 0,
    })


@admin_required
def add_product(request):
    if request.method == 'POST':
        name  = request.POST.get('name', '').strip()
        brand = get_object_or_404(Brand, id=request.POST.get('brand'))
        
        image_file = request.FILES.get('image')
        image_result = _handle_image_upload(request, image_file)
        if image_result == "TOO_LARGE":
            return redirect('add_product')

        Product.objects.create(
            brand=brand, name=name,
            price=request.POST.get('price'),
            stock=request.POST.get('stock'),
            primary_image=image_result,
        )
        messages.success(request, f"Product '{name}' added!")
        return redirect('show_products')
    return render(request, 'add_product.html', {'brands': Brand.objects.all()})


@admin_required
def show_products(request):
    return render(request, 'show_products.html', {
        'products': Product.objects.select_related('brand', 'category').all()
    })


@admin_required
def edit_product(request, id):
    product = get_object_or_404(Product, id=id)
    if request.method == 'POST':
        product.name  = request.POST.get('name', '').strip()
        product.price = request.POST.get('price')
        product.stock = request.POST.get('stock')
        product.brand = get_object_or_404(Brand, id=request.POST.get('brand'))
        
        image_file = request.FILES.get('image')
        if image_file:
            image_result = _handle_image_upload(request, image_file)
            if image_result == "TOO_LARGE":
                return redirect('edit_product', id=product.id)
            product.primary_image = image_result

        product.save()
        messages.success(request, "Product updated!")
        return redirect('show_products')
    return render(request, 'edit_product.html', {'product': product, 'brands': Brand.objects.all()})


@admin_required
def delete_product(request, id):
    get_object_or_404(Product, id=id).delete()
    messages.success(request, "Product deleted.")
    return redirect('show_products')


@admin_required
def show_brands(request):
    return render(request, 'show_brands.html', {'brands': Brand.objects.all()})


@admin_required
def add_brand(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        image_file = request.FILES.get('image')
        image_result = _handle_image_upload(request, image_file)
        if image_result == "TOO_LARGE":
            return redirect('add_brand')

        Brand.objects.create(
            name=name,
            image=image_result,
        )
        messages.success(request, "Brand added!")
        return redirect('show_brands')
    return render(request, 'add_brand.html')


@admin_required
def edit_brand(request, id):
    brand = get_object_or_404(Brand, id=id)
    if request.method == 'POST':
        brand.name = request.POST.get('name', '').strip()
        image_file = request.FILES.get('image')
        if image_file:
            image_result = _handle_image_upload(request, image_file)
            if image_result == "TOO_LARGE":
                return redirect('edit_brand', id=brand.id)
            brand.image = image_result
        brand.save()
        messages.success(request, "Brand updated!")
        return redirect('show_brands')
    return render(request, 'edit_brand.html', {'brand': brand})


@admin_required
def delete_brand(request, id):
    get_object_or_404(Brand, id=id).delete()
    messages.success(request, "Brand deleted.")
    return redirect('show_brands')


@admin_required
def approval_page(request):
    return render(request, 'approval_page.html', {
        'users': UserProfile.objects.filter(is_admin=False)
    })


@admin_required
def approve_user(request, id):
    user = get_object_or_404(UserProfile, id=id)
    user.status = '1'
    user.save()
    messages.success(request, "User approved.")
    return redirect('approval_page')


@admin_required
def disapprove_user(request, id):
    user = get_object_or_404(UserProfile, id=id)
    user.status = '0'
    user.save()
    messages.warning(request, "User disabled.")
    return redirect('approval_page')


@admin_required
def view_users(request):
    return render(request, 'view_users.html', {
        'users': UserProfile.objects.filter(is_admin=False)
    })


@admin_required
def delete_user(request, id):
    get_object_or_404(UserProfile, id=id).delete()
    messages.success(request, "User deleted.")
    return redirect('view_users')


# ======================================================
# CUSTOMER STOREFRONT
# ======================================================

@user_login_required
def user_home(request):
    user = get_object_or_404(UserProfile, id=request.session['user_id'])
    return render(request, 'user_home.html', {'user': user, 'brands': Brand.objects.all()})


@user_login_required
def brand_products(request, brand_id):
    brand = get_object_or_404(Brand, id=brand_id)
    user  = get_object_or_404(UserProfile, id=request.session['user_id'])
    products = Product.objects.filter(brand=brand, is_active=True).prefetch_related('variants')
    return render(request, 'brand_products.html', {
        'brand': brand, 'products': products,
        'user': user, 'brands': Brand.objects.all(),
    })


# ======================================================
# CART
# ======================================================

@user_login_required
def add_to_cart(request, product_id):
    user    = get_object_or_404(UserProfile, id=request.session['user_id'])
    product = get_object_or_404(Product, id=product_id)
    qty     = int(request.POST.get('quantity', 1))

    cart_item, created = Cart.objects.get_or_create(user=user, product=product)
    cart_item.quantity = cart_item.quantity + qty if not created else qty
    cart_item.save()

    messages.success(request, f"'{product.name}' added to cart!")
    return redirect('view_cart')


@user_login_required
def view_cart(request):
    user       = get_object_or_404(UserProfile, id=request.session['user_id'])
    cart_items = Cart.objects.select_related('product').filter(user=user)
    total      = sum(item.total_price for item in cart_items)

    return render(request, 'view_cart.html', {
        'user': user, 'brands': Brand.objects.all(),
        'cart_items': cart_items, 'total_price': total,
        'cart_count': cart_items.count(),
    })


@user_login_required
def remove_cart_item(request, item_id):
    get_object_or_404(Cart, id=item_id).delete()
    return redirect('view_cart')


def update_cart_quantity(request):
    """AJAX endpoint — update quantity of a single cart item."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    cart_item = get_object_or_404(Cart, id=request.POST.get('cart_id'))
    new_qty   = int(request.POST.get('quantity', 0))

    if new_qty <= 0:
        cart_item.delete()
        return JsonResponse({'removed': True})

    cart_item.quantity = new_qty
    cart_item.save()
    total = float(sum(item.total_price for item in Cart.objects.filter(user=cart_item.user)))
    return JsonResponse({'removed': False, 'item_total': float(cart_item.total_price), 'total_price': total})


# ======================================================
# CHECKOUT & MOCK PAYMENT
# ======================================================

@user_login_required
def checkout_order(request):
    """Step 1 — Validate cart, show mock payment page. Stock NOT deducted yet."""
    if request.method != 'POST':
        return redirect('view_cart')

    user         = get_object_or_404(UserProfile, id=request.session['user_id'])
    selected_ids = request.POST.getlist('selected_items')
    cart_items   = Cart.objects.select_related('product').filter(user=user, id__in=selected_ids)

    if not cart_items.exists():
        messages.warning(request, "No items selected for checkout.")
        return redirect('view_cart')

    # Stock validation
    for item in cart_items:
        if item.product.stock < item.quantity:
            messages.error(request, f"Not enough stock for {item.product.name}. Only {item.product.stock} left.")
            return redirect('view_cart')

    subtotal, tax, shipping, grand_total = _calculate_totals(cart_items)
    request.session['pending_checkout_items'] = selected_ids

    return render(request, 'mock_payment.html', {
        'user': user, 'brands': Brand.objects.all(),
        'selected_ids': selected_ids,
        'total_price': subtotal,
        'tax': tax, 'shipping': shipping, 'grand_total': grand_total,
    })


@user_login_required
@transaction.atomic
def process_payment(request):
    """Step 2 — User paid. Create order, deduct stock, clear cart."""
    if request.method != 'POST':
        return redirect('view_cart')

    user         = get_object_or_404(UserProfile, id=request.session['user_id'])
    selected_ids = request.session.pop('pending_checkout_items', None)

    if not selected_ids:
        messages.error(request, "Checkout session expired. Please try again.")
        return redirect('view_cart')

    cart_items = Cart.objects.select_related('product').filter(user=user, id__in=selected_ids)

    if not cart_items.exists():
        messages.warning(request, "Cart items not found.")
        return redirect('view_cart')

    # Final stock validation (race condition guard)
    for item in cart_items:
        if item.product.stock < item.quantity:
            messages.error(request, f"Sorry, '{item.product.name}' just went out of stock!")
            return redirect('view_cart')

    subtotal, tax, shipping, grand_total = _calculate_totals(cart_items)

    order = Order.objects.create(
        user=user, total_amount=subtotal, tax_amount=tax,
        shipping_cost=shipping, grand_total=grand_total,
        status='Pending', payment_status='Paid',
    )

    for item in cart_items:
        OrderItem.objects.create(
            order=order, product=item.product,
            quantity=item.quantity,
            price_at_purchase=item.product.discount_price or item.product.price,
        )
        item.product.stock = max(0, item.product.stock - item.quantity)
        if item.product.stock == 0:
            item.product.is_active = False
        item.product.save(update_fields=['stock', 'is_active'])

    cart_items.delete()
    messages.success(request, f"Payment successful! Order #{order.id} placed. 🎉")
    return redirect('my_orders')


@user_login_required
def my_orders(request):
    user   = get_object_or_404(UserProfile, id=request.session['user_id'])
    orders = Order.objects.filter(user=user).prefetch_related('items__product').order_by('-created_at')
    return render(request, 'my_orders.html', {'user': user, 'orders': orders, 'brands': Brand.objects.all()})


@user_login_required
def cancel_order_item(request, item_id):
    item = get_object_or_404(OrderItem, id=item_id)

    if item.order.user.id != request.session.get('user_id'):
        messages.error(request, "Unauthorized.")
        return redirect('my_orders')

    if item.order.status != 'Pending':
        messages.error(request, "You can only cancel pending orders.")
        return redirect('my_orders')

    # Restore stock
    item.product.stock += item.quantity
    item.product.is_active = True
    item.product.save(update_fields=['stock', 'is_active'])
    item.delete()

    # Cancel whole order if no items left
    if not item.order.items.exists():
        item.order.status = 'Cancelled'
        item.order.save(update_fields=['status'])

    messages.success(request, "Item cancelled and stock restored.")
    return redirect('my_orders')


# ======================================================
# STORE, SEARCH & PRODUCT DETAIL
# ======================================================

def search_products(request):
    query       = request.GET.get('q', '')
    brand_id    = request.GET.get('brand')
    category_id = request.GET.get('category')
    min_price   = request.GET.get('min_price')
    max_price   = request.GET.get('max_price')
    sort_by     = request.GET.get('sort', 'newest')

    products = (
        Product.objects
        .filter(is_active=True)
        .annotate(avg_rating=Avg('reviews__rating'), review_count=Count('reviews'))
        .prefetch_related('variants')
    )

    if query:
        products = products.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(brand__name__icontains=query)
        )
    if brand_id:
        products = products.filter(brand_id=brand_id)
    if category_id:
        products = products.filter(category_id=category_id)
    if min_price:
        products = products.filter(price__gte=min_price)
    if max_price:
        products = products.filter(price__lte=max_price)

    sort_map = {'price_low': 'price', 'price_high': '-price', 'newest': '-created_at'}
    products = products.order_by(sort_map.get(sort_by, '-created_at'))

    page_obj = Paginator(products, 12).get_page(request.GET.get('page'))

    return render(request, 'store.html', {
        'page_obj':        page_obj,
        'user':            _get_logged_in_user(request),
        'current_q':       query,
        'current_brand':   brand_id,
        'current_category': category_id,
        'current_min':     min_price,
        'current_max':     max_price,
        'current_sort':    sort_by,
    })


def product_detail(request, id):
    product    = get_object_or_404(Product.objects.prefetch_related('reviews__user'), id=id)
    reviews    = product.reviews.order_by('-created_at')
    avg_rating = round(reviews.aggregate(avg=Avg('rating'))['avg'] or 0, 1)
    user       = _get_logged_in_user(request)

    if request.method == 'POST' and user:
        comment = request.POST.get('comment', '').strip()
        rating  = int(request.POST.get('rating', 5))
        if ProductReview.objects.filter(product=product, user=user).exists():
            messages.warning(request, "You have already reviewed this product.")
        else:
            ProductReview.objects.create(product=product, user=user, rating=rating, comment=comment)
            messages.success(request, "Thank you for your review! ⭐")
            return redirect('product_detail', id=product.id)

    return render(request, 'product_detail.html', {
        'product':    product,
        'reviews':    reviews,
        'avg_rating': avg_rating,
        'user':       user,
        'brands':     Brand.objects.all(),
    })


# ======================================================
# CUSTOM ERROR HANDLERS
# ======================================================

def custom_403(request, exception=None):
    return render(request, '403.html', status=403)

def custom_404(request, exception):
    return render(request, '404.html', status=404)


def custom_500(request):
    return render(request, '500.html', status=500)