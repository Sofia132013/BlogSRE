from django import forms
from django.forms import ModelForm, Textarea
from django.utils.text import slugify

from .models import Comment, Group, Post


class PostForm(ModelForm):
    class Meta:
        model = Post
        fields = ["group", "text", "image"]
        required = {
            "group": False,
        }
        labels = {
            "group": "Категория",
            "text": "Текст записи",
            "image": "Картинка"
        }
        help_texts = {
            "group": "Выберите категорию для публикации или оставьте поле пустым."
        }


class CategoryForm(ModelForm):
    class Meta:
        model = Group
        fields = ("title", "description")
        labels = {
            "title": "Название категории",
            "description": "Описание",
        }
        help_texts = {
            "title": "Например: Путешествия, Музыка или Городская жизнь.",
            "description": "Коротко расскажите, о чём будут публикации в этой категории.",
        }
        widgets = {"description": Textarea(attrs={"rows": 4})}

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if Group.objects.filter(title__iexact=title).exists():
            raise forms.ValidationError("Категория с таким названием уже существует.")
        return title

    def save(self, commit=True):
        category = super().save(commit=False)
        base_slug = slugify(category.title) or "category"
        slug = base_slug
        number = 2
        while Group.objects.filter(slug=slug).exclude(pk=category.pk).exists():
            slug = "{0}-{1}".format(base_slug, number)
            number += 1
        category.slug = slug
        if commit:
            category.save()
        return category


class CommentForm(ModelForm):
    class Meta:
        model = Comment
        fields = ("text",)
        widgets = {
            "text": Textarea
        }
        labels = {
            "text": "Комментарий"
        }
        error_messages = {
            "text": {
                "required": "Напишите комментарий перед отправкой.",
            }
        }
