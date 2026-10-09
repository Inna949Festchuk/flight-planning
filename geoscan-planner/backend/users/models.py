from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    email = models.EmailField("email", unique=True)
    full_name = models.CharField("полное имя", max_length=128, blank=True)

    def __str__(self):
        return self.username
