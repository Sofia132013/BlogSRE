import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from posts.models import Group, Post


ACCOUNTS = (
    {
        "username": "alina_travel",
        "first_name": "Алина",
        "last_name": "Романова",
        "email": "alina.travel@example.com",
        "group": ("Путешествия", "travel", "Маршруты, города и открытия в пути."),
        "post": "Три часа без карты в Тбилиси — и это оказался лучший маршрут\n\nЯ свернула с главной улицы за запахом свежего хлеба и вышла к тихому двору с виноградной лозой. Иногда полезно оставить план в рюкзаке и просто идти туда, где интересно.",
    },
    {
        "username": "mikhail_code",
        "first_name": "Михаил",
        "last_name": "Орлов",
        "email": "mikhail.code@example.com",
        "group": ("Технологии", "technology", "Код, продукты и идеи, которые меняют привычные вещи."),
        "post": "Почему маленькие инструменты часто приживаются лучше больших платформ\n\nУ хорошего инструмента есть одно понятное действие и короткий путь до результата. Когда задача решается за минуту, к продукту хочется возвращаться каждый день.",
    },
    {
        "username": "sofia_books",
        "first_name": "София",
        "last_name": "Белова",
        "email": "sofia.books@example.com",
        "group": ("Книги", "books", "Чтение, заметки и истории, которые хочется обсуждать."),
        "post": "Книга, к которой я возвращаюсь каждую осень\n\nЕсть истории, которые читаются по-разному в зависимости от того, где ты сейчас. В этот раз я особенно заметила второстепенных героев — и поняла, что именно они держат весь сюжет.",
    },
    {
        "username": "nika_kitchen",
        "first_name": "Ника",
        "last_name": "Соколова",
        "email": "nika.kitchen@example.com",
        "group": ("Еда", "food", "Простые рецепты, сезонные продукты и удовольствие от готовки."),
        "post": "Ужин на одной сковороде: лимон, томаты и паста\n\nПока варится паста, обжарьте чеснок и томаты на оливковом масле. Добавьте немного воды от пасты, цедру лимона и щедрую горсть зелени — получается быстро и очень по-летнему.",
    },
    {
        "username": "lev_balance",
        "first_name": "Лев",
        "last_name": "Кузнецов",
        "email": "lev.balance@example.com",
        "group": ("Баланс", "balance", "Привычки, спорт и способы бережно организовать день."),
        "post": "Одна привычка, которая вернула мне спокойное утро\n\nЯ перестал начинать день с уведомлений. Первые двадцать минут теперь принадлежат завтраку, блокноту и короткой прогулке до кофе. Рабочих задач меньше не стало, но в них появилось больше ясности.",
    },
    {
        "username": "daria_learn",
        "first_name": "Дарья",
        "last_name": "Волкова",
        "email": "daria.learn@example.com",
        "group": ("Образование", "education", "Учёба, языки и знания, которые помогают двигаться дальше."),
        "post": "Как я вернула привычку учиться по двадцать минут в день\n\nЯ перестала ждать свободного вечера и стала выбирать одну маленькую тему на неделю. Пара заметок после завтрака оказалась устойчивее, чем длинные списки целей.",
    },
    {
        "username": "artem_sport",
        "first_name": "Артём",
        "last_name": "Лебедев",
        "email": "artem.sport@example.com",
        "group": ("Спорт", "sport", "Тренировки, движение и здоровый азарт."),
        "post": "Бег без рекордов: зачем оставлять в плане лёгкие тренировки\n\nНе каждая пробежка должна быть проверкой силы. В спокойном темпе легче заметить дыхание, ритм шага и то самое удовольствие, ради которого хочется выйти снова.",
    },
)

EXTRA_CATEGORIES = (
    ("Искусство", "art", "Выставки, иллюстрация, фотография и творческие находки."),
    ("Музыка", "music", "Новые альбомы, концерты и песни на повторе."),
    ("Кино", "cinema", "Фильмы, сериалы и истории с большого экрана."),
    ("Наука", "science", "Открытия, исследования и понятные объяснения сложного."),
    ("Карьера", "career", "Работа, профессиональный рост и полезные навыки."),
    ("Дом", "home", "Уют, интерьер, растения и маленькие домашние ритуалы."),
    ("Природа", "nature", "Прогулки, наблюдения и бережное отношение к миру вокруг."),
    ("Игры", "games", "Настольные игры, видеоигры и истории о любимых мирах."),
)


class Command(BaseCommand):
    help = "Создаёт 7 демо-авторов, публикации и 15 тематических категорий Blog."

    def handle(self, *args, **options):
        user_model = get_user_model()
        missing_accounts = [
            data for data in ACCOUNTS
            if not user_model.objects.filter(username=data["username"]).exists()
        ]
        demo_password = os.getenv("BLOG_DEMO_PASSWORD")
        if missing_accounts and not demo_password:
            raise CommandError(
                "Set BLOG_DEMO_PASSWORD before creating demo accounts."
            )

        accounts_created = 0
        posts_created = 0
        categories_created = 0

        for data in ACCOUNTS:
            group_title, group_slug, group_description = data["group"]
            group, _ = Group.objects.update_or_create(
                slug=group_slug,
                defaults={"title": group_title, "description": group_description},
            )
            user, created = user_model.objects.get_or_create(
                username=data["username"],
                defaults={
                    "first_name": data["first_name"],
                    "last_name": data["last_name"],
                    "email": data["email"],
                },
            )
            if created:
                user.set_password(demo_password)
                user.save()
                accounts_created += 1
            post, post_created = Post.objects.get_or_create(
                author=user,
                text=data["post"],
                defaults={"group": group},
            )
            if not post_created and post.group != group:
                post.group = group
                post.save(update_fields=["group"])
            posts_created += int(post_created)

        for title, slug, description in EXTRA_CATEGORIES:
            _, created = Group.objects.get_or_create(
                slug=slug,
                defaults={"title": title, "description": description},
            )
            categories_created += int(created)

        self.stdout.write(self.style.SUCCESS(
            "Готово: создано аккаунтов — {0}, публикаций — {1}, "
            "дополнительных категорий — {2}.".format(
                accounts_created, posts_created, categories_created
            )
        ))
