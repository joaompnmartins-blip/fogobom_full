from django.conf import settings


def map_keys(request):
    return {'carto_api_key': settings.CARTO_API_KEY}
