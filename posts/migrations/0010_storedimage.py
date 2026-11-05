from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posts", "0009_alter_group_options"),
    ]

    operations = [
        migrations.CreateModel(
            name="StoredImage",
            fields=[
                ("name", models.CharField(max_length=100, primary_key=True, serialize=False)),
                ("content", models.BinaryField()),
                ("size", models.PositiveIntegerField()),
            ],
        ),
    ]
