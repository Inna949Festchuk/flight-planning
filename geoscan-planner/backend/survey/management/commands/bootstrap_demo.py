from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = "Создаёт демо-пользователя demo/demo и суперпользователя admin"

    def handle(self, *args, **options):
        if not User.objects.filter(username="demo").exists():
            User.objects.create_user(
                username="demo", email="demo@geoscan.local", password="demo", full_name="Демо"
            )
            self.stdout.write("Создан демо-пользователь demo/demo")
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser(
                username="admin", email="admin@geoscan.local", password="admin123", full_name="Администратор"
            )
            self.stdout.write("Создан суперпользователь admin/admin123")
