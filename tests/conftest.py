import os

os.environ.setdefault('DJANGO_SECRET_KEY', 'test-only-not-a-deployment-secret')
os.environ.setdefault('DJANGO_DEBUG', 'true')

pytest_plugins = [
    'tests.fixtures.fixture_user',
    'tests.fixtures.fixture_data',
]
