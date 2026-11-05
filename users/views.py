import logging

from django.db import transaction
from django.views.generic import CreateView
from django.urls import reverse_lazy
from .forms import CreationForm, ContactForm
from django.shortcuts import redirect, render

from blog.metrics import USER_REGISTRATIONS
from blog.slo_demo import business_attempt


activity_logger = logging.getLogger("blog.activity")


class SignUp(CreateView):
    form_class = CreationForm
    success_url = reverse_lazy("login")  # where login is the "name" parameter in path()
    template_name = "users/signup.html"

    def form_valid(self, form):
        fault = business_attempt("registration")
        if fault is not None:
            return fault
        response = super().form_valid(form)
        transaction.on_commit(USER_REGISTRATIONS.inc)
        activity_logger.info("user.registered actor_id=%s", self.object.pk)
        return response


def user_contact(request):

    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            return redirect('/thank-you/')
        return render(request, 'contact.html', {'form': form})
    form = ContactForm()
    return render(request, 'contact.html', {form: form})
