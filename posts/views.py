import logging

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from blog.metrics import COMMENTS_CREATED, POSTS_CREATED, SUBSCRIPTIONS_CREATED
from blog.slo_demo import business_attempt, demo_response

from .forms import CategoryForm, CommentForm, PostForm
from .models import Follow, Group, Post, User


activity_logger = logging.getLogger("blog.activity")


def index(request):
    """
    Gets a selection of 10 entries per page.
    :param request:
    :return: page "index.html"
    """
    fault = demo_response()
    if fault is not None:
        return fault
    post_list = Post.objects.all()
    paginator = Paginator(post_list, 10)
    page_number = request.GET.get("page")
    page = paginator.get_page(page_number)
    return render(request, "index.html", {"page": page, "paginator": paginator}
                  )


def group_posts(request, slug):
    """
    Gets an object from the database and outputs new entries by criteria.
    If the object is not found it reports a 404 error.

    :param request:
    :param slug:
    :return: page "group.html"
    """
    group = get_object_or_404(Group, slug=slug)
    posts = group.posts.all()
    paginator = Paginator(posts, 10)
    page_number = request.GET.get("page")
    page = paginator.get_page(page_number)

    return render(request, "group.html",
                  {"group": group,
                   "page": page,
                   "paginator": paginator, }
                  )


@login_required
def categories(request):
    category_list = Group.objects.annotate(post_count=Count("posts")).order_by("title")
    return render(request, "categories.html", {"categories": category_list})


@login_required
def new_category(request):
    form = CategoryForm(request.POST or None)
    if form.is_valid():
        category = form.save()
        activity_logger.info(
            "category.created actor_id=%s category_id=%s", request.user.pk, category.pk
        )
        return redirect("categories")
    return render(request, "posts/new_category.html", {"form": form})


@login_required
def new_post(request):
    """
    Adds a new publication.
    :param request:
    :return: After validating the form and creating a new post,
    the author is redirected to the main page.
    """
    # Let"s assume that the http request body can"t be empty, then:
    form = PostForm(request.POST or None, files=request.FILES or None)
    if not form.is_valid():
        return render(request, "posts/new_post.html", {"form": form, "is_edit": False})
    fault = business_attempt("post")
    if fault is not None:
        return fault
    post = form.save(commit=False)
    post.author = request.user
    post.save()
    transaction.on_commit(POSTS_CREATED.inc)
    activity_logger.info("post.created actor_id=%s post_id=%s", request.user.pk, post.pk)
    return redirect("index")


def profile(request, username):
    """
    Adds a profile page with posts
    :param request:
    :param username:
    :return: page "profile.html"
    """
    author = get_object_or_404(User, username=username)
    following = False
    if request.user.is_authenticated:
        following = Follow.objects.filter(user=request.user.id,
                                          author=author).exists()

    post_list = author.author_posts.all()
    count_posts = post_list.count()
    paginator = Paginator(post_list, 10)
    page_number = request.GET.get("page")
    page = paginator.get_page(page_number)

    return render(request, "profile.html", {
        "author": author,
        "page": page,
        "paginator": paginator,
        "count_posts": count_posts,
        "profile": author,
        "following": following})


def post_view(request, username, post_id):
    """
    Creates a Page for viewing a separate post
    :param request:
    :param username:
    :param post_id:
    :return: page "post_view.html"
    """
    fault = demo_response()
    if fault is not None:
        return fault
    author = get_object_or_404(User, username=username)
    post = get_object_or_404(Post, pk=post_id, author__username=username)
    count_posts = author.author_posts.count()
    following = False
    if request.user.is_authenticated:
        following = Follow.objects.filter(
            user=request.user, author=author
        ).exists()

    form = CommentForm()
    comments = post.comments.all()

    return render(request, "post_view.html", {
        "author": author,
        "username": username,
        "post": post,
        "count_posts": count_posts,
        "following": following,
        "form": form,
        "comments": comments, })


@login_required
def post_edit(request, username, post_id):
    """
    Creating a page for editing an existing post
    :param request:
    :param username:
    :param post_id:
    :return: the page with the changed post or the page for viewing the post.
    """
    post = get_object_or_404(Post, pk=post_id, author__username=username)
    if request.user != post.author:
        activity_logger.warning(
            "post.edit_denied actor_id=%s post_id=%s", request.user.pk, post.pk
        )
        return redirect("post_view", username=username, post_id=post_id)

    form = PostForm(request.POST or None, files=request.FILES or None, instance=post)
    if not form.is_valid():
        return render(request, "posts/new_post.html", {
            "form": form,
            "post": post,
            "is_edit": True})
    form.save()
    activity_logger.info("post.updated actor_id=%s post_id=%s", request.user.pk, post.pk)
    return redirect("post_view", username=username, post_id=post_id)


@login_required
@require_POST
def post_delete(request, username, post_id):
    """Delete a post only when it belongs to the current user."""
    post = get_object_or_404(Post, pk=post_id, author__username=username)
    if request.user != post.author:
        activity_logger.warning(
            "post.delete_denied actor_id=%s post_id=%s", request.user.pk, post.pk
        )
        return redirect("post_view", username=username, post_id=post_id)
    post.delete()
    activity_logger.info("post.deleted actor_id=%s post_id=%s", request.user.pk, post_id)
    return redirect("index")


@login_required
def add_comment(request, username, post_id):
    """
    Creating a comment for editing an existing post
    :param request:
    :param username:
    :param post_id:
    :return: the page with comment or the page for viewing the post.
    """
    post = get_object_or_404(Post, pk=post_id, author__username=username)
    form = CommentForm(request.POST)
    if not form.is_valid():
        author = post.author
        following = Follow.objects.filter(
            user=request.user, author=author
        ).exists()
        return render(request, "post_view.html", {
            "author": author,
            "username": author.username,
            "post": post,
            "count_posts": author.author_posts.count(),
            "following": following,
            "form": form,
            "comments": post.comments.all(),
        })
    fault = business_attempt("comment")
    if fault is not None:
        return fault
    comment = form.save(commit=False)
    comment.author = request.user
    comment.post = post
    form.save()
    activity_logger.info(
        "comment.created actor_id=%s comment_id=%s post_id=%s",
        request.user.pk, comment.pk, post.pk,
    )
    transaction.on_commit(COMMENTS_CREATED.inc)
    return redirect("post_view", username, post_id)


@login_required
def follow_index(request):
    """
    Displays posts of authors that the current user is subscribed to.
    :param request:
    :return: the page with posts of authors that the current user is subscribed to.
    """
    author = get_object_or_404(User, username=request.user)
    post_list = Post.objects.filter(author__following__user=request.user)
    count_posts = post_list.count()
    paginator = Paginator(post_list, 10)
    page_number = request.GET.get("page")
    page = paginator.get_page(page_number)

    return render(request, "follow.html",
                  {"author": author,
                   "count_posts": count_posts,
                   "page": page,
                   "paginator": paginator,
                   })


@login_required
@require_POST
def profile_follow(request, username):
    """
    Subscribes to an interesting author.
    """
    author = get_object_or_404(User, username=username)
    follow = Follow.objects.filter(user=request.user, author=author).exists()
    if not request.user == author and follow is False:
        Follow.objects.create(user=request.user, author=author)
        transaction.on_commit(SUBSCRIPTIONS_CREATED.inc)
        activity_logger.info(
            "follow.created actor_id=%s author_id=%s", request.user.pk, author.pk
        )
    return redirect("profile", username=username)


@login_required
@require_POST
def profile_unfollow(request, username):
    """
    Unsubscribes from the author.
    """
    author = get_object_or_404(User, username=username)
    deleted, _ = Follow.objects.filter(user=request.user, author=author).delete()
    if deleted:
        activity_logger.info(
            "follow.deleted actor_id=%s author_id=%s", request.user.pk, author.pk
        )
    return redirect("profile", username=username)


def page_not_found(request, exception):  # noqa
    return render(request, "misc/404.html", {"path": request.path}, status=404)


def server_error(request):
    return render(request, "misc/500.html", status=500)
