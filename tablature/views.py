# coding: utf-8

from __future__ import unicode_literals
import json

from django.db.models import FieldDoesNotExist, Q
from django.db.models.query import QuerySet
from django.http import HttpResponse
from django.utils.encoding import force_text
from django.utils.http import urlunquote
from django.utils.text import capfirst
from django.views.generic import ListView, TemplateView, View
from django.views.generic.list import MultipleObjectMixin


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
    pass


class TableDataViewMixin:
    columns = ()
    columns_widths = {}
    verbose_columns = {}
    search_lookups = ()
    orderings = {}
    filters = {}
    results_per_page = 15
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

    def get_config(self):
        columns = self.get_columns()
        return {
            'columns': [force_text(self.get_verbose_column(c))
                        for c in columns],
            'columns_widths': [self.get_column_width(c) for c in columns],
            'search_enabled': bool(self.search_lookups),
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
        if not q:
            return queryset
        filters = Q()
        for lookup in self.search_lookups:
            filters |= Q(**{lookup: q})
        if filters:
            return queryset.filter(filters)
        return queryset.none()

    def get_results_queryset(self):
        GET = self.request.GET
        qs = self.get_queryset()
        qs = self.search(qs, GET.get('q'))
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

    def get_results(self):
        results = []
        for obj in self.get_limited_results_queryset():
            row = []
            for attr in self.get_columns():
                verbose_attr = 'get_' + attr + '_display'
                if hasattr(obj, verbose_attr):
                    attr = verbose_attr
                v = getattr(obj, attr)
                if callable(v):
                    v = v()
                v = '' if v is None else force_text(v)
                row.append(v)
            results.append(row)
        return results

    def get_data(self):
        return {'results': self.get_results(),
                'count': self.get_results_queryset().count()}

    def get_json_response(self):
        data = (self.get_config() if 'get_config' in self.request.GET
                else self.get_data())
        response = HttpResponse(json.dumps(data),
                                content_type='application/json')
        if self.access_control_allow_origin:
            response['Access-Control-Allow-Origin'] = \
                self.access_control_allow_origin
        return response


class TableDataView(TableDataViewMixin, MultipleObjectMixin, View):
    def get(self, request, *args, **kwargs):
        return self.get_json_response()


class TableView(TablePageViewMixin, TableDataViewMixin, ListView):
    def get(self, request, *args, **kwargs):
        if request.is_ajax():
            return self.get_json_response()
        return super(TableView, self).get(request, *args, **kwargs)
