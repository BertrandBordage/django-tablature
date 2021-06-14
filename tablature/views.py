# coding: utf-8

from __future__ import unicode_literals

from django.contrib.postgres.search import SearchVector, SearchQuery
from django.db import connections
from django.db.models import FieldDoesNotExist, Q
from django.db.models.query import QuerySet
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.utils.encoding import force_text
from django.utils.http import urlunquote
from django.utils.text import capfirst
from django.utils.translation import get_language
from django.views.decorators.cache import never_cache
from django.views.generic import ListView, TemplateView, View
from django.views.generic.list import MultipleObjectMixin


class ModelMixin:
    def __init__(self, *args, **kwargs):
        super(ModelMixin, self).__init__(*args, **kwargs)
        if self.model is None:
            self.model = self.queryset.model


class TablePageViewMixin:
    template_name = 'tablature/table_page.html'
    ajax_url = ''

    def get_ajax_url(self):
        return self.ajax_url

    def get_context_data(self, **kwargs):
        context = super(TablePageViewMixin, self).get_context_data(**kwargs)
        context.update(
            verbose_name_plural=self.model._meta.verbose_name_plural,
            ajax_url=self.get_ajax_url(),
        )
        return context


class TablePageView(TablePageViewMixin, TemplateView):
    model = None


class TableDataViewMixin(ModelMixin):
    columns = ()
    columns_widths = {}
    verbose_columns = {}
    search_lookups = ()
    orderings = {}
    filters = {}
    results_per_page = 15
    postgresql_search_configs = {
        'da': 'danish',
        'nl': 'dutch',
        'en': 'english',
        'fi': 'finnish',
        'fr': 'french',
        'de': 'german',
        'hu': 'hungarian',
        'it': 'italian',
        'nb': 'norwegian',
        'nn': 'norwegian',
        'pt': 'portuguese',
        'ro': 'romanian',
        'ru': 'russian',
        'es': 'spanish',
        'sv': 'swedish',
        'tr': 'turkish',
    }
    access_control_allow_origin = ''

    def get_columns(self):
        if self.columns:
            return self.columns
        return [f.name for f in self.model._meta.fields]

    def get_field(self, column):
        try:
            return self.model._meta.get_field(column)
        except FieldDoesNotExist:
            pass

    def get_verbose_column(self, column):
        if column in self.verbose_columns:
            return self.verbose_columns[column]
        field = self.get_field(column)
        if field is None:
            method = getattr(self.model, column)
            if hasattr(method, 'short_description'):
                column = method.short_description
        else:
            column = field.verbose_name
        return capfirst(column)

    def get_column_width(self, column):
        if column in self.columns_widths:
            return self.columns_widths[column]
        return 'initial'

    @property
    def search_enabled(self):
        return bool(self.search_lookups)

    def get_config(self):
        columns = self.get_columns()
        return {
            'columns': [force_text(self.get_verbose_column(c))
                        for c in columns],
            'columns_widths': [self.get_column_width(c) for c in columns],
            'search_enabled': self.search_enabled,
            'sortables': [bool(self.get_ordering_for_column(c, 1))
                          for c in columns],
            'filters': [self.get_filter(c) for c in columns],
            'results_per_page': self.results_per_page,
        }

    def get_ordering_for_column(self, column, direction):
        """
        Returns a tuple of lookups to order by for the given column
        and direction. Direction is an integer, either -1, 0 or 1.
        """
        if direction == 0:
            return ()
        if column in self.orderings:
            ordering = self.orderings[column]
        else:
            field = self.get_field(column)
            if field is None:
                return ()
            ordering = column
        if not isinstance(ordering, (tuple, list)):
            ordering = [ordering]
        if direction == 1:
            return ordering
        return [lookup[1:] if lookup[0] == '-' else '-' + lookup
                for lookup in ordering]

    def get_filter(self, column):
        if column not in self.filters:
            return ()
        values = self.filters[column]
        if isinstance(values, QuerySet):
            values = tuple(values.all())
        assert len(values[0]) == 2, 'Each filter must be a value/verbose pair.'
        return values

    def search(self, queryset, q):
        if connections[queryset.db].vendor == 'postgresql':
            language_code = get_language().split('-', 1)[0]
            search_config = self.postgresql_search_configs.get(language_code)
            return queryset.annotate(
                search=SearchVector(*self.search_lookups, config=search_config)
            ).filter(search=SearchQuery(q, config=search_config))
        filters = Q()
        for lookup in self.search_lookups:
            filters |= Q(**{lookup: q})
        if filters:
            return queryset.filter(filters)
        return queryset.none()

    def get_results_queryset(self):
        GET = self.request.GET
        qs = self.get_queryset()
        q = urlunquote(GET.get('q', '')).strip()
        if q:
            qs = self.search(qs, q)
        columns = self.get_columns()

        filter_choices = map(urlunquote, GET.get('choices', '').split(','))
        for column, choice in zip(columns, filter_choices):
            if choice:
                method = getattr(self, 'filter_' + column, None)
                qs = (qs.filter(**{column: choice}) if method is None
                      else method(qs, choice))

        if 'orderings' in GET:
            order_directions = map(int, GET.get('orderings', '').split(','))
        else:
            order_directions = [0] * len(columns)
        order_by = []
        for column, direction in zip(columns, order_directions):
            order_by.extend(self.get_ordering_for_column(column, direction))
        if order_by:
            qs = qs.order_by(*order_by)
        return qs.distinct()

    def get_limited_results_queryset(self):
        qs = self.get_results_queryset()
        current_page = int(self.request.GET.get('page', '0'))
        offset = current_page * self.results_per_page
        return qs[offset:offset + self.results_per_page]

    def get_value(self, obj, attr):
        method = getattr(self, 'get_' + attr + '_display', None)
        if method is not None:
            return method(obj)
        v = getattr(obj, 'get_' + attr + '_display', None)
        if v is None:
            v = getattr(obj, attr)
        if callable(v):
            v = v()
        return v

    def get_results(self):
        results = []
        for obj in self.get_limited_results_queryset():
            row = []
            for attr in self.get_columns():
                v = self.get_value(obj, attr)
                row.append('' if v is None else force_text(v))
            results.append(row)
        return results

    def get_data(self):
        return {'results': self.get_results(),
                'count': self.get_results_queryset().count()}

    def get_json_response(self):
        data = (self.get_config() if 'get_config' in self.request.GET
                else self.get_data())
        response = JsonResponse(data)
        if self.access_control_allow_origin:
            response['Access-Control-Allow-Origin'] = \
                self.access_control_allow_origin
        return response


class TableDataView(TableDataViewMixin, MultipleObjectMixin, View):
    def get(self, request, *args, **kwargs):
        return self.get_json_response()


# Never caching fixes an issue with Chrome 63 where the browser returns
# the cached AJAX response instead of the HTML response when we use "previous".
@method_decorator(never_cache, name='dispatch')
class TableView(TablePageViewMixin, TableDataViewMixin, ListView):
    def get(self, request, *args, **kwargs):
        if request.is_ajax():
            return self.get_json_response()
        return super(TableView, self).get(request, *args, **kwargs)
