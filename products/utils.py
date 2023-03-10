from django import forms
from django.db.models import Q
from django.forms.utils import ErrorDict
from django.http import HttpResponseRedirect, QueryDict
from django.shortcuts import render
from django.views.generic.edit import ContextMixin, FormView
from django.views.generic import TemplateView

from mainapp.utils.utils import filter_data
from mainapp.models import UserCompany

from .models import Product, Category
from .forms import ProductForm

from slugify import slugify

from typing import List, Tuple, Optional


def del_errors(form: forms.Form, del_fields: List[str]) -> forms.Form:
    form.is_valid()
    for field in del_fields:
        form.errors[field] = ErrorDict()

    return form


def dict_to_list(obj: dict) -> List[Tuple[str, str]]:
    result = []
    for key in obj:
        result.append((key, obj[key]))

    return result


def str_to_python_var(string) -> str:
    return slugify(string).replace('-', '_')


def form_to_dict(form_data: dict, additional_exclude: tuple) -> Tuple[dict, dict]:
    # we send only list of base fields of class Product
    exclude_fields = list(ProductForm.__dict__['base_fields'].keys())
    exclude_fields.extend(additional_exclude)

    return filter_data(exclude_fields, form_data)


class ParseNewForm:

    def form_to_dict(self, form_data: dict) -> Tuple[dict, dict]:
        # we send only list of base fields of class Product
        exclude_fields = list(self.form_class.declared_fields.keys())
        exclude_fields.append('csrfmiddlewaretoken')

        return filter_data(exclude_fields, form_data)

    def get_form_by_post(self, post_data: QueryDict):
        clear_data = post_data.dict()
        filter_form = self.form_to_dict(clear_data)[1]
        # in `filter_form` we get data from POST request that haven't in base form
        new_class_form = type('NewClassForm', (self.form_class,),
                              {field_key: forms.CharField() for field_key in filter_form})
        # in 'new_class_form' we crete new form that contains all fields from POST request

        return new_class_form(post_data)


class DFFMixin(FormView, ParseNewForm):

    def post(self, request, *args, **kwargs):
        form = self.get_form_by_post(request.POST)
        if form.is_valid():
            print('form valid')
            return self.form_valid(form)
        else:
            print('form invalid')
            return self.form_invalid(form)


class TransformForm:

    def transform_to_new_form(self, form: forms.Form):
        form_data = form.cleaned_data
        data = filter_data(['key', 'value'], form.__class__.__dict__['base_fields'])
        form_fields = data[1]
        form_fields[str_to_python_var(form_data['key'])] = forms.CharField(label=form_data['key'])

        new_class_from = type('NewClassForm', (forms.Form,), form_fields)

        form_data[str_to_python_var(form_data['key'])] = form_data['value']

        return new_class_from(form_data)


class FinalCreateMixin(ParseNewForm):

    def form_valid(self, form):
        print('valid create')
        if self.media_files_list == list(self.request.FILES.dict().keys()):
            print('----')
            remain_data, parameters = form_to_dict(form.cleaned_data)
            remain_data.update(self.request.FILES.dict())
            return self.create_new_object(remain_data, parameters)
        else:

            media_form = type('MediaForm', (form.__class__,),
                {
                    key: value for key, value in self.form_class.declared_fields.items()
                    if key in self.media_files_list
                }
            )

            new_form = del_errors(media_form(form.cleaned_data), self.media_files_list)

            return render(
                self.request, 'products/create_product.html', {'form': new_form}
            )

    def create_new_object(self, remain_data: dict, parameters: dict) -> HttpResponseRedirect:
        obj = Product.objects.create(**remain_data, parameters=parameters)

        return HttpResponseRedirect(obj.get_absolute_url())


class ProductsQuery:
    """
    ???????????????? ???????????? id ?????????????????? categories
    ???????????????? ???????????? id ???????????????? companies
    ???????????????? ??????????, ?????????????? ???????????????? ?????????????? ?????????????????? ?????? (???? X)
    ???????????????? ??????????, ?????????????? ???????????????? ???????????? ?????????????????? ?????? (???? X)
    """
    companies: list = []
    categories: list = []
    price__gte: int = None
    price__lte: int = None

    def __init__(self, query: dict):
        if 'categories' in query.keys():
            self.categories = self.get_categories(query['categories'])['category_set']
        if 'companies' in query.keys():
            self.companies = self.get_companies(query['companies'])['company_set']

        if 'from' and 'to' in query.keys():
            price_gap = self.get_price_gap(query['from'], query['to'])
            self.price__gte = price_gap['price__gte']
            self.price__lte = price_gap['price__lte']

    @staticmethod
    def get_categories(categories: str) -> dict:
        """
        :param categories: ???????????? ???? id ???????????? Category, ????????????: `1, 23, 45`
        :return: ?????????????? ?? ???????????? `category_set` ?? ???????????????? list ???? id
        """
        return {'category_set': categories.split(',')}

    @staticmethod
    def get_companies(companies: str) -> dict:
        """
        :param companies: ?????????????????????? ????????????????, ?????? ?? ?????????????? `get_categories`
        ???????????? ???????????????????????? ?????????? Company
        """
        return {'company_set': companies.split(',')}

    @staticmethod
    def get_price_gap(from_: Optional[str], to: Optional[str]) -> dict:
        """
        :param from_: ?????????? `????` ?? ???????? ????????????
        :param to: ?????????? `????` ?? ???????? ????????????
        :return: ?????????????? ?? ?????????? ??????????????
        ???????????? ?? ???????????? `price__gte` ?? ???????????????? `form_`
        ???????????? ?? ???????????? `price__lte` ?? ???????????????? `to`
        """

        if not from_ and to:
            return {'price__gte': None, 'price__lte': None}
        elif not to:
            return {'price__gte': int(from_), 'price__lte': None}
        elif not from_:
            return {'price__lte': None, 'price_lte': int(to)}
        elif from_ and to:
            return {'price__gte': int(from_), 'price__lte': int(to)}


class SeveralQuerySetMixin:

    def get_all_queries(self, products_query: ProductsQuery):
        categories = self.get_category_queries(products_query.categories)
        companies = self.get_company_queries(products_query.companies)
        from_price = Q(price__gte=products_query.price__gte) if products_query.price__gte else Q()
        to_price = Q(price__lte=products_query.price__lte) if products_query.price__lte else Q()

        return Product.objects.filter(categories | companies & from_price & to_price).distinct()

    @staticmethod
    def get_category_queries(categories: list) -> Q:
        data = Q()
        for cat in categories:
            data |= Q(category_set=cat)

        return data

    @staticmethod
    def get_company_queries(companies: list) -> Q:
        data = Q(pk=-1)
        for company in companies:
            data |= Q(user_company=company)

        return data


class SelectedList:

    @staticmethod
    def get_categories_list(query: ProductsQuery):
        # Set default query data in `pk=-1` for if query list is empty we'll find nothing
        data = Q(pk=-1)
        for cat in query.categories:
            data |= Q(pk=cat)

        active_categories = Category.objects.filter(data)
        filter_active_categories = [
            (
                'checked', category.name, category.pk
            )
            for category in active_categories
        ]
        filter_unselect_categories = [
            (
                '',
                category.name,
                category.pk
            ) for category in Category.objects.filter(level='level3')[:10] if not category in active_categories
        ]

        return filter_active_categories + filter_unselect_categories

    @staticmethod
    def get_companies_list(query: ProductsQuery) -> list:
        data = Q(pk=-1)
        for com in query.companies:
            data |= Q(pk=com)

        companies = UserCompany.objects.filter(data).select_related('user')
        active_companies = [
            (
                'checked', company.user.username, company.pk
            ) for company in companies
        ]
        unselect_companies = [
            (
                '',
                company.user.username,
                company.pk
            ) for company in UserCompany.objects.order_by('product_set')[:10] if not company in companies
        ]

        return active_companies + unselect_companies


def get_feedback_context(request, obj) -> dict:

    context = {'feedback_set': obj.feedback_set.all()}
    if not obj.feedback_set.filter(user_who_put=request.user).exists():
        context['exist_create_form'] = True

    return context
