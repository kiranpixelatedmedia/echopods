from .models import Cart, UserProfile

def cart_count(request):
    count = 0
    if request.session.get('user_id'):
        try:
            user = UserProfile.objects.get(id=request.session['user_id'])
            count = Cart.objects.filter(user=user).count()
        except UserProfile.DoesNotExist:
            pass
    return {'cart_count': count}

from .models import Brand

def all_brands(request):
    return {'brands': Brand.objects.all()}

