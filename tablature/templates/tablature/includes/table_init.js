{% load i18n %}

$(function () {
  var filters = [
    {% for filter in filters %}
      [
        {% for value, verbose in filter %}
          ['{{ value|escapejs }}','{{ verbose|escapejs }}']{% if not forloop.last %},{% endif %}
        {% endfor %}
      ]{% if not forloop.last %},{% endif %}
    {% endfor %}
  ];
  new Table(
    $('#table'), ['{{ columns|join:"','" }}'],
    ['{{ columns_widths|join:"','" }}'],
    [{{ sortables|join:',' }}], filters,
    {{ results_per_page }}, '{% trans 'results' %}',
    '{% trans 'Sort by this column' %}',
    '{% trans 'Filter by this column' %}',
    '{% trans 'Clear selection' %}'
  );
});
