from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "full_name"]
        read_only_fields = ["id"]


class RegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["username", "email", "password", "full_name"]
        extra_kwargs = {"password": {"write_only": True, "style": {"input_type": "password"}}}

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)
