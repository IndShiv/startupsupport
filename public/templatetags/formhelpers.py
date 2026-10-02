from django import template

register = template.Library()


def described_by(field):
    ids = []
    if field.help_text:
        ids.append(f"{field.auto_id}_helptext")
    if field.errors:
        ids.append(f"{field.auto_id}_error")
    if field.field.widget.attrs.get("data-max-words"):
        ids.append(f"{field.auto_id}_counter")
    return " ".join(ids)


@register.filter
def accessible(field):
    """Render a widget with aria-describedby pointing at its help text, error and word counter."""
    attrs = {}
    ids = described_by(field)
    if ids:
        attrs["aria-describedby"] = ids
    if field.errors:
        attrs["aria-invalid"] = "true"
    return field.as_widget(attrs=attrs)


@register.filter
def describedby(field):
    return described_by(field)


@register.filter
def in_list(value, items):
    return value in items


@register.filter
def person(user, fallback="–"):
    """A user's full name, their username, or the fallback when there is no user."""
    if not user:
        return fallback
    return user.get_full_name() or user.username
