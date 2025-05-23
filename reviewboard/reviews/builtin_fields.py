from __future__ import annotations

import logging
import uuid
from itertools import chain
from typing import (Any, Generic, Iterable, Mapping, Optional, Sequence,
                    TYPE_CHECKING, cast)

from django.db import models
from django.template.loader import get_template, render_to_string
from django.urls import NoReverseMatch
from django.utils.functional import cached_property
from django.utils.html import escape, format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.translation import gettext, gettext_lazy as _
from typing_extensions import TypeVar

from reviewboard.accounts.models import User
from reviewboard.attachments.models import FileAttachment
from reviewboard.diffviewer.diffutils import get_sorted_filediffs
from reviewboard.diffviewer.models import DiffCommit, DiffSet
from reviewboard.reviews.fields import (BaseCommaEditableField,
                                        BaseEditableField,
                                        BaseReviewRequestField,
                                        BaseReviewRequestFieldSet,
                                        BaseTextAreaField,
                                        TFieldValue)
from reviewboard.reviews.models import (Group, ReviewRequest,
                                        ReviewRequestDraft,
                                        Screenshot)
from reviewboard.scmtools.models import Repository
from reviewboard.site.urlresolvers import local_site_reverse

if TYPE_CHECKING:
    from django.utils.safestring import SafeString
    from djblets.webapi.responses import WebAPIResponsePayload

    from reviewboard.changedescs.models import ChangeDescription
    from reviewboard.reviews.detail import ReviewRequestPageData
    from reviewboard.reviews.fields import ReviewRequestFieldChangeEntrySection
    from reviewboard.reviews.models.base_review_request_details import \
        BaseReviewRequestDetails

    FieldMixinParent = BaseReviewRequestField
else:
    FieldMixinParent = Generic


logger = logging.getLogger(__name__)


#: A generic type for a model passed to a review request field.
#:
#: Version Added:
#:     7.1
TModel = TypeVar('TModel', bound=models.Model)


class BuiltinFieldMixin(FieldMixinParent[TFieldValue]):
    """Mixin for built-in fields.

    This overrides some functions to work with native fields on a
    ReviewRequest or ReviewRequestDraft, rather than working with those
    stored in extra_data.
    """

    def __init__(self, *args, **kwargs) -> None:
        """Initialize the field.

        Args:
            *args (tuple):
                Positional arguments to pass through to the superclass.

            **kwargs (dict):
                Keyword arguments to pass through to the superclass.
        """
        super().__init__(*args, **kwargs)

        field_id = self.field_id
        assert field_id is not None

        review_request_details = self.review_request_details

        if (not hasattr(review_request_details, field_id) and
            isinstance(review_request_details, ReviewRequestDraft)):
            # This field only exists in ReviewRequest, and not in
            # the draft, so we're going to work there instead.
            review_request_details = \
                review_request_details.get_review_request()

    def load_value(
        self,
        review_request_details: BaseReviewRequestDetails,
    ) -> Optional[TFieldValue]:
        """Load a value from the review request or draft.

        Args:
            review_request_details (reviewboard.reviews.models.
                                    base_review_request_details.
                                    BaseReviewRequestDetails):
                The review request or draft.

        Returns:
            object:
            The loaded value.
        """
        field_id = self.field_id
        assert field_id

        value = getattr(review_request_details, field_id)

        if isinstance(value, models.Manager):
            value = list(value.all())

        return cast(Optional[TFieldValue], value)

    def save_value(
        self,
        value: Optional[TFieldValue],
    ) -> None:
        """Save the value in the review request or draft.

        Args:
            value (object):
                The new value for the field.
        """
        field_id = self.field_id
        assert field_id

        field = getattr(self.review_request_details, field_id)

        # ManyRelatedManager cannot be set with a simple assignment, so we need
        # to use .set() for that. Other field types can use setattr.
        if isinstance(field, models.Manager):
            field.set(value)
        else:
            setattr(self.review_request_details, field_id, value)


class BuiltinTextAreaFieldMixin(BuiltinFieldMixin[str]):
    """Mixin for built-in text area fields.

    This will ensure that the text is always rendered in Markdown,
    no matter whether the source text is plain or Markdown. It will
    still escape the text if it's not in Markdown format before
    rendering.
    """

    def get_data_attributes(self) -> dict[str, Any]:
        """Return any data attributes to include in the element.

        Returns:
            dict:
            The data attributes to include in the element.
        """
        attrs = super().get_data_attributes()

        # This is already available in the review request state fed to the
        # page, so we don't need it in the data attributes as well.
        attrs.pop('raw-value', None)

        return attrs


class ReviewRequestPageDataMixin(FieldMixinParent[TFieldValue]):
    """Mixin for internal fields needing access to the page data.

    These are used by fields that operate on state generated when creating the
    review request page. The view handling that page makes a lot of queries,
    and stores the results. This mixin allows access to those results,
    preventing additional queries.

    The data structure is not meant to be public API, and this mixin should not
    be used by any classes outside this file.

    By default, this will not render or handle any value loading or change
    entry recording. Subclasses must implement those manually.
    """

    #: Whether the field should be rendered.
    should_render: bool = False

    ######################
    # Instance variables #
    ######################

    #: The data already queried for the review request page.
    data: Optional[ReviewRequestPageData]

    def __init__(
        self,
        review_request_details: BaseReviewRequestDetails,
        data: Optional[ReviewRequestPageData] = None,
        *args,
        **kwargs,
    ) -> None:
        """Initialize the mixin.

        Args:
            review_request_details (reviewboard.reviews.models.
                                    base_review_request_details.
                                    BaseReviewRequestDetails):
                The review request (or the active draft thereof). In practice
                this will either be a
                :py:class:`reviewboard.reviews.models.ReviewRequest` or a
                :py:class:`reviewboard.reviews.models.ReviewRequestDraft`.

            data (reviewboard.reviews.detail.ReviewRequestPageData):
                The data already queried for the review request page.

            *args (tuple):
                Additional positional arguments.

            **kwargs (dict):
                Additional keyword arguments.
        """
        super().__init__(review_request_details, *args, **kwargs)

        self.data = data

    def load_value(
        self,
        review_request_details: BaseReviewRequestDetails,
    ) -> Optional[TFieldValue]:
        """Load a value from the review request or draft.

        Args:
            review_request_details (reviewboard.reviews.models.
                                    base_review_request_details.
                                    BaseReviewRequestDetails):
                The review request or draft.

        Returns:
            object:
            The loaded value.
        """
        return None

    def record_change_entry(
        self,
        changedesc: ChangeDescription,
        old_value: Any,
        new_value: Any,
    ) -> None:
        """Record information on the changed values in a ChangeDescription.

        Args:
            changedesc (reviewboard.changedescs.models.ChangeDescription):
                The change description to record the entry in.

            old_value (object):
                The old value of the field.

            new_value (object):
                The new value of the field.
        """
        pass


class BaseCaptionsField(ReviewRequestPageDataMixin[str],
                        BaseReviewRequestField[str]):
    """Base class for rendering captions for attachments.

    This serves as a base for FileAttachmentCaptionsField and
    ScreenshotCaptionsField. It provides the base rendering and
    for caption changes on file attachments or screenshots.
    """

    obj_map_attr: Optional[str] = None
    caption_object_field: Optional[str] = None

    change_entry_renders_inline = False

    def render_change_entry_html(
        self,
        info: object,
    ) -> SafeString:
        """Render a change entry to HTML.

        This function is expected to return safe, valid HTML. Any values
        coming from a field or any other form of user input must be
        properly escaped.

        Args:
            info (dict):
                A dictionary describing how the field has changed. This is
                guaranteed to have ``new`` and ``old`` keys, but may also
                contain ``added`` and ``removed`` keys as well.

        Returns:
            django.utils.safestring.SafeString:
            The HTML representation of the change entry.
        """
        assert isinstance(info, dict)

        data = self.data
        obj_map_attr = self.obj_map_attr

        assert data is not None
        assert obj_map_attr is not None

        render_item = super().render_change_entry_html
        obj_map = getattr(data, obj_map_attr)

        s = ['<table class="caption-changed">']

        for id_str, caption in info.items():
            obj = obj_map[int(id_str)]

            s.append(format_html(
                '<tr>'
                ' <th><a href="{url}">{filename}</a>:</th>'
                ' <td>{caption}</td>'
                '</tr>',
                url=obj.get_absolute_url(),
                filename=obj.filename,
                caption=mark_safe(render_item(caption))))

        s.append('</table>')

        return mark_safe(''.join(s))

    def serialize_change_entry(
        self,
        changedesc: ChangeDescription,
    ) -> Sequence[WebAPIResponsePayload]:
        """Serialize a change entry for public consumption.

        This will output a version of the change entry for use in the API.
        It can be the same content stored in the
        :py:class:`~reviewboard.changedescs.models.ChangeDescription`, but
        does not need to be.

        Args:
            changedesc (reviewboard.changedescs.models.ChangeDescription):
                The change description whose field is to be serialized.

        Returns:
            list:
            An appropriate serialization for the field.
        """
        data = changedesc.fields_changed[self.field_id]

        model = self.model
        assert model is not None

        return [
            {
                'old': data[str(obj.pk)]['old'][0],
                'new': data[str(obj.pk)]['new'][0],
                self.caption_object_field: obj,
            }
            for obj in model.objects.filter(pk__in=data.keys())
        ]


class BaseModelListEditableField(BaseCommaEditableField[TModel]):
    """Base class for editable comma-separated list of model instances.

    This is used for built-in classes that work with ManyToManyFields.
    """

    model_name_attr: Optional[str] = None

    def has_value_changed(
        self,
        old_value: Sequence[TModel],
        new_value: Sequence[TModel],
    ) -> bool:
        """Return whether the value has changed.

        Args:
            old_value (object):
                The old value of the field.

            new_value (object):
                The new value of the field.

        Returns:
            bool:
            Whether the value of the field has changed.
        """
        old_values = {obj.pk for obj in old_value}
        new_values = {obj.pk for obj in new_value}

        return old_values != new_values

    def record_change_entry(
        self,
        changedesc: ChangeDescription,
        old_value: Sequence[TModel],
        new_value: Sequence[TModel],
    ) -> None:
        """Record information on the changed values in a ChangeDescription.

        Args:
            changedesc (reviewboard.changedescs.models.ChangeDescription):
                The change description to record the entry in.

            old_value (object):
                The old value of the field.

            new_value (object):
                The new value of the field.
        """
        assert self.field_id

        changedesc.record_field_change(field=self.field_id,
                                       old_value=old_value,
                                       new_value=new_value,
                                       name_field=self.model_name_attr)

    def render_change_entry_item_html(
        self,
        info: object,
        item: tuple[str, str, int],
    ) -> SafeString:
        """Render an item for change description HTML.

        Args:
            info (dict):
                A dictionary describing how the field has changed.

            item (object):
                The value of the item.

        Returns:
            django.utils.safestring.SafeString:
            The rendered change entry.
        """
        label, url, pk = item

        if url:
            return format_html('<a href="{}">{}</a>', url, label)
        else:
            return escape(label)

    def save_value(
        self,
        value: Optional[Sequence[TModel]],
    ) -> None:
        """Save the value in the review request or draft.

        Args:
            value (object):
                The new value for the field.
        """
        assert self.field_id

        setattr(self.review_request_details, self.field_id, value)


class StatusField(BuiltinFieldMixin[str],
                  BaseReviewRequestField[str]):
    """The Status field on a review request."""

    field_id = 'status'
    label = _('Status')
    is_required = True

    #: Whether the field should be rendered.
    should_render = False

    def get_change_entry_sections_html(
        self,
        info: object,
    ) -> Sequence[ReviewRequestFieldChangeEntrySection]:
        """Return sections of change entries with titles and rendered HTML.

        Because the status field is specially handled, this just returns an
        empty list.

        Args:
            info (dict, unused):
                A dictionary describing how the field has changed.

        Returns:
            list:
            An empty list.
        """
        return []


class SummaryField(BuiltinFieldMixin, BaseEditableField):
    """The Summary field on a review request."""

    field_id = 'summary'
    label = _('Summary')
    is_required = True
    tag_name = 'h1'

    #: The class name for the JavaScript view representing this field.
    js_view_class = 'RB.ReviewRequestFields.SummaryFieldView'


class DescriptionField(BuiltinTextAreaFieldMixin, BaseTextAreaField):
    """The Description field on a review request."""

    field_id = 'description'
    label = _('Description')
    is_required = True

    #: The class name for the JavaScript view representing this field.
    js_view_class = 'RB.ReviewRequestFields.DescriptionFieldView'

    def is_text_markdown(
        self,
        value: Optional[str],
    ) -> bool:
        """Return whether the description uses Markdown.

        Args:
            value (str, unused):
                The field's text.

        Returns:
            bool:
            True if the description field should be formatted using Markdown.
        """
        return self.review_request_details.description_rich_text


class TestingDoneField(BuiltinTextAreaFieldMixin, BaseTextAreaField):
    """The Testing Done field on a review request."""

    field_id = 'testing_done'
    label = _('Testing Done')

    #: The class name for the JavaScript view representing this field.
    js_view_class = 'RB.ReviewRequestFields.TestingDoneFieldView'

    def is_text_markdown(
        self,
        value: Optional[str],
    ) -> bool:
        """Return whether the description uses Markdown.

        Args:
            value (str, unused):
                The field's text.

        Returns:
            bool:
            True if the description field should be formatted using Markdown.
        """
        return self.review_request_details.testing_done_rich_text


class OwnerField(BuiltinFieldMixin[User],
                 BaseEditableField[User]):
    """The Owner field on a review request."""

    field_id = 'submitter'
    label = _('Owner')
    model = User
    model_name_attr = 'username'
    is_required = True

    #: The class name for the JavaScript view representing this field.
    js_view_class = 'RB.ReviewRequestFields.OwnerFieldView'

    def render_value(
        self,
        value: Optional[User],
    ) -> SafeString:
        """Render the value in the field.

        Args:
            value (django.contrib.auth.models.User):
                The value to render.

        Returns:
            django.utils.safestring.SafeString:
            The rendered value.
        """
        assert value is not None

        user = value
        request = self.request
        review_request_details = self.review_request_details

        assert request is not None
        assert review_request_details is not None

        return format_html(
            '<a class="user" href="{0}">{1}</a>',
            local_site_reverse(
                'user',
                local_site=review_request_details.local_site,
                args=[user]),
            user.get_profile().get_display_name(request.user))

    def record_change_entry(
        self,
        changedesc: ChangeDescription,
        old_value: User,
        new_value: User,
    ) -> None:
        """Record information on the changed values in a ChangeDescription.

        Args:
            changedesc (reviewboard.changedescs.models.ChangeDescription):
                The change description to record the entry in.

            old_value (django.contrib.auth.models.User):
                The old value of the field.

            new_value (django.contrib.auth.models.User):
                The new value of the field.
        """
        field_id = self.field_id
        assert field_id

        changedesc.record_field_change(
            field=field_id,
            old_value=old_value,
            new_value=new_value,
            name_field=self.model_name_attr,
            build_url_func=lambda user: local_site_reverse(
                'user',
                local_site=self.review_request_details.local_site,
                kwargs={
                    'username': user.username,
                }))

    def render_change_entry_value_html(
        self,
        info: object,
        value: tuple[str, str, int],
    ) -> SafeString:
        """Render the value for a change description string to HTML.

        Args:
            info (dict):
                A dictionary describing how the field has changed.

            item (object):
                The value of the field.

        Returns:
            django.utils.safestring.SafeString:
            The rendered change entry.
        """
        label, url, pk = value

        if url:
            return format_html('<a href="{}">{}</a>', url, label)
        else:
            return escape(label)

    def serialize_change_entry(
        self,
        changedesc: ChangeDescription,
    ) -> WebAPIResponsePayload:
        """Serialize a change entry for public consumption.

        This will output a version of the change entry for use in the API.
        It can be the same content stored in the
        :py:class:`~reviewboard.changedescs.models.ChangeDescription`, but
        does not need to be.

        Args:
            changedesc (reviewboard.changedescs.models.ChangeDescription):
                The change description whose field is to be serialized.

        Returns:
            dict:
            An appropriate serialization for the field.
        """
        entry = super().serialize_change_entry(changedesc)
        assert isinstance(entry, dict)

        return {
            key: value[0]
            for key, value in entry.items()
        }


class RepositoryField(BuiltinFieldMixin[Repository],
                      BaseReviewRequestField[Repository]):
    """The Repository field on a review request."""

    field_id = 'repository'
    label = _('Repository')
    model = Repository

    @property
    def should_render(self) -> bool:
        """Whether the field should be rendered."""
        review_request = self.review_request_details.get_review_request()

        return review_request.repository_id is not None


class BranchField(BuiltinFieldMixin[str],
                  BaseEditableField[str]):
    """The Branch field on a review request."""

    field_id = 'branch'
    label = _('Branch')

    #: The class name for the JavaScript view representing this field.
    js_view_class = 'RB.ReviewRequestFields.BranchFieldView'


class BugsField(BuiltinFieldMixin[Sequence[str]],
                BaseCommaEditableField[str]):
    """The Bugs field on a review request."""

    field_id = 'bugs_closed'
    label = _('Bugs')

    one_line_per_change_entry = False

    #: The class name for the JavaScript view representing this field.
    js_view_class = 'RB.ReviewRequestFields.BugsFieldView'

    def load_value(
        self,
        review_request_details: BaseReviewRequestDetails,
    ) -> Sequence[str]:
        """Load a value from the review request or draft.

        Args:
            review_request_details (reviewboard.reviews.models.
                                    base_review_request_details.
                                    BaseReviewRequestDetails):
                The review request or draft.

        Returns:
            object:
            The loaded value.
        """
        return review_request_details.get_bug_list()

    def save_value(
        self,
        value: Optional[Sequence[str]],
    ) -> None:
        """Save the value in the review request or draft.

        Args:
            value (object):
                The new value for the field.
        """
        assert self.field_id

        setattr(self.review_request_details, self.field_id, (
            ', '.join(value or [])
            .replace('\n', '')
            .replace('\r', '')
        ))

    def render_item(
        self,
        item: str,
    ) -> SafeString:
        """Render an item from the list.

        Args:
            item (object):
                The item to render.

        Returns:
            django.utils.safestring.SafeString:
            The rendered item.
        """
        bug_url = self._get_bug_url(item)

        if bug_url:
            return format_html('<a class="bug" href="{url}">{id}</a>',
                               url=bug_url,
                               id=item)
        else:
            return escape(item)

    def render_change_entry_item_html(
        self,
        info: object,
        item: tuple[str, str, int],
    ) -> SafeString:
        """Render an item for change description HTML.

        Args:
            info (dict):
                A dictionary describing how the field has changed.

            item (object):
                The value of the item.

        Returns:
            django.utils.safestring.SafeString:
            The rendered change entry.
        """
        return self.render_item(item[0])

    def _get_bug_url(
        self,
        bug_id: str,
    ) -> Optional[str]:
        """Return the URL to link to a specific bug.

        Args:
            bug_id (str):
                The ID of the bug to link to.

        Returns:
            str:
            The link to view the bug in the bug tracker, if available.
        """
        review_request_details = self.review_request_details
        review_request = review_request_details.get_review_request()
        repository = review_request_details.repository
        local_site_name: Optional[str] = None
        bug_url: Optional[str] = None

        if review_request.local_site:
            local_site_name = review_request.local_site.name

        try:
            if (repository and
                repository.bug_tracker and
                '%s' in repository.bug_tracker):
                bug_url = local_site_reverse(
                    'bug_url', local_site_name=local_site_name,
                    args=[review_request.display_id, bug_id])
        except NoReverseMatch:
            pass

        return bug_url


class DependsOnField(BuiltinFieldMixin[Sequence[ReviewRequest]],
                     BaseModelListEditableField[ReviewRequest]):
    """The Depends On field on a review request."""

    field_id = 'depends_on'
    label = _('Depends On')
    model = ReviewRequest
    model_name_attr = 'summary'

    #: The class name for the JavaScript view representing this field.
    js_view_class = 'RB.ReviewRequestFields.DependsOnFieldView'

    def render_change_entry_item_html(
        self,
        info: object,
        item: tuple[str, str, int],
    ) -> SafeString:
        """Render an item for change description HTML.

        Args:
            info (dict):
                A dictionary describing how the field has changed.

            item (object):
                The value of the item.

        Returns:
            django.utils.safestring.SafeString:
            The rendered change entry.
        """
        obj = ReviewRequest.objects.get(pk=item[2])

        rendered_item = format_html(
            '<a href="{url}">{id} - {summary}</a>',
            url=obj.get_absolute_url(),
            id=obj.pk,
            summary=obj.summary)

        if obj.status in (ReviewRequest.SUBMITTED,
                          ReviewRequest.DISCARDED):
            rendered_item = format_html('<s>{}</s>', rendered_item)

        return rendered_item

    def render_item(
        self,
        item: ReviewRequest,
    ) -> SafeString:
        """Render an item from the list.

        Args:
            item (object):
                The item to render.

        Returns:
            django.utils.safestring.SafeString:
            The rendered item.
        """
        rendered_item = format_html(
            '<a href="{url}" title="{summary}"'
            '   class="review-request-link">{id}</a>',
            url=item.get_absolute_url(),
            summary=item.summary,
            id=item.display_id)

        if item.status in (ReviewRequest.SUBMITTED,
                           ReviewRequest.DISCARDED):
            rendered_item = format_html('<s>{}</s>', rendered_item)

        return rendered_item


class BlocksField(BuiltinFieldMixin[Sequence[ReviewRequest]],
                  BaseReviewRequestField[Sequence[ReviewRequest]]):
    """The Blocks field on a review request."""

    field_id = 'blocks'
    label = _('Blocks')
    model = ReviewRequest

    def load_value(
        self,
        review_request_details: BaseReviewRequestDetails,
    ) -> Optional[Sequence[ReviewRequest]]:
        """Load a value from the review request or draft.

        Args:
            review_request_details (reviewboard.reviews.models.
                                    base_review_request_details.
                                    BaseReviewRequestDetails):
                The review request or draft.

        Returns:
            object:
            The loaded value.
        """
        return review_request_details.get_review_request().get_blocks()

    @property
    def should_render(self) -> bool:
        """Whether the field should be rendered."""
        return bool(self.value)

    def render_value(
        self,
        value: Optional[Sequence[ReviewRequest]],
    ) -> SafeString:
        """Render the value in the field.

        Args:
            blocks (list):
                The value to render.

        Returns:
            django.utils.safestring.SafeString:
            The rendered value.
        """
        return format_html_join(
            ', ',
            '<a href="{0}" class="review-request-link">{1}</a>',
            [
                (item.get_absolute_url(), item.display_id)
                for item in (value or [])
            ])


class ChangeField(BuiltinFieldMixin[str],
                  BaseReviewRequestField[str]):
    """The Change field on a review request.

    This is shown for repositories supporting changesets. The change
    number is similar to a commit ID, with the exception that it's only
    ever stored on the ReviewRequest and never changes.

    If both ``changenum`` and ``commit_id`` are provided on the review
    request, only this field will be shown, as both are likely to have
    values.
    """

    field_id = 'changenum'
    label = _('Change')

    def load_value(
        self,
        review_request_details: BaseReviewRequestDetails,
    ) -> str:
        """Load a value from the review request or draft.

        Args:
            review_request_details (reviewboard.reviews.models.
                                    base_review_request_details.
                                    BaseReviewRequestDetails):
                The review request or draft.

        Returns:
            str:
            The loaded value.
        """
        return review_request_details.get_review_request().changenum

    @property
    def should_render(self) -> bool:
        """Whether the field should be rendered."""
        return bool(self.value)

    def render_value(
        self,
        value: Optional[str],
    ) -> SafeString:
        """Render the value in the field.

        Args:
            changenum (str):
                The value to render.

        Returns:
            django.utils.safestring.SafeString:
            The rendered value.
        """
        review_request = self.review_request_details.get_review_request()

        is_pending, changenum = review_request.changeset_is_pending(value)

        if is_pending:
            fmt = gettext('{} (pending)')
        else:
            fmt = '{}'

        return format_html(fmt, changenum)


class CommitField(BuiltinFieldMixin[str],
                  BaseReviewRequestField[str]):
    """The Commit field on a review request.

    This displays the ID of the commit the review request is representing.

    Since the ``commit_id`` and ``changenum`` fields are both populated, we
    let ChangeField take precedence. It knows how to render information based
    on a changeset ID.
    """

    field_id = 'commit_id'
    label = _('Commit')
    can_record_change_entry = True
    tag_name = 'span'

    @property
    def should_render(self) -> bool:
        """Whether the field should be rendered."""
        return (bool(self.value) and
                not self.review_request_details.get_review_request().changenum)

    def render_value(
        self,
        value: Optional[str],
    ) -> SafeString:
        """Render the value in the field.

        Args:
            commit_id (str):
                The value to render.

        Returns:
            django.utils.safestring.SafeString:
            The rendered value.
        """
        assert value is not None

        # Abbreviate SHA-1s
        commit_id = value

        if len(commit_id) == 40:
            abbrev_commit_id = commit_id[:7] + '...'

            return format_html('<span title="{}">{}</span>',
                               commit_id,
                               abbrev_commit_id)
        else:
            return escape(commit_id)


class DiffField(ReviewRequestPageDataMixin[DiffSet],
                BuiltinFieldMixin[DiffSet],
                BaseReviewRequestField[DiffSet]):
    """Represents a newly uploaded diff on a review request.

    This is not shown as an actual displayable field on the review request
    itself. Instead, it is used only during the ChangeDescription population
    and processing steps.
    """

    field_id = 'diff'
    label = _('Diff')

    can_record_change_entry = True

    MAX_FILES_PREVIEW = 8

    def render_change_entry_html(
        self,
        info: object,
    ) -> SafeString:
        """Render a change entry to HTML.

        This function is expected to return safe, valid HTML. Any values
        coming from a field or any other form of user input must be
        properly escaped.

        Args:
            info (dict):
                A dictionary describing how the field has changed. This is
                guaranteed to have ``new`` and ``old`` keys, but may also
                contain ``added`` and ``removed`` keys as well.

        Returns:
            django.utils.safestring.SafeString:
            The HTML representation of the change entry.
        """
        assert isinstance(info, dict)

        added_diff_info = info['added'][0]
        review_request = self.review_request_details.get_review_request()

        data = self.data
        assert data is not None

        try:
            diffset = data.diffsets_by_id[added_diff_info[2]]
        except KeyError:
            # If a published revision of a diff has been deleted from the
            # database, this will explode. Just return a blank string for this,
            # so that it doesn't show a traceback.
            return mark_safe('')

        diff_revision = diffset.revision
        past_revision = diff_revision - 1
        diff_url = added_diff_info[1]

        s: list[SafeString] = []

        # Fetch the total number of inserts/deletes. These will be shown
        # alongside the diff revision.
        counts = diffset.get_total_line_counts()
        raw_insert_count = counts.get('raw_insert_count', 0)
        raw_delete_count = counts.get('raw_delete_count', 0)

        line_counts = []

        if raw_insert_count > 0:
            line_counts.append('<span class="insert-count">+%d</span>'
                               % raw_insert_count)

        if raw_delete_count > 0:
            line_counts.append('<span class="delete-count">-%d</span>'
                               % raw_delete_count)

        # Display the label, URL, and line counts for the diff.
        if line_counts:
            s.append(format_html(
                '<p class="diff-changes">'
                ' <a href="{url}">{label}</a>'
                ' <span class="line-counts">({line_counts})</span>'
                '</p>',
                url=diff_url,
                label=_('Revision %s') % diff_revision,
                line_counts=mark_safe(' '.join(line_counts))))
        else:
            s.append(format_html(
                '<p class="diff-changes">'
                ' <a href="{url}">{label}</a>'
                '</p>',
                url=diff_url,
                label=_('Revision %s') % diff_revision))

        if past_revision > 0:
            # This is not the first diff revision. Include an interdiff link.
            interdiff_url = local_site_reverse(
                'view-interdiff',
                local_site=review_request.local_site,
                args=[
                    review_request.display_id,
                    past_revision,
                    diff_revision,
                ])

            s.append(format_html(
                '<p><a href="{url}">{text}</a>',
                url=interdiff_url,
                text=_('Show changes')))

        file_count = len(diffset.cumulative_files)

        if file_count > 0:
            # Begin displaying the list of files modified in this diff.
            # It will be capped at a fixed number (MAX_FILES_PREVIEW).
            s += [
                mark_safe('<div class="diff-index">'),
                mark_safe(' <table>'),
            ]

            # We want a sorted list of filediffs, but tagged with the order in
            # which they come from the database, so that we can properly link
            # to the respective files in the diff viewer.
            files = get_sorted_filediffs(enumerate(diffset.cumulative_files),
                                         key=lambda i: i[1])

            for i, filediff in files[:self.MAX_FILES_PREVIEW]:
                counts = filediff.get_line_counts()

                data_attrs = [
                    'data-%s="%s"' % (attr.replace('_', '-'), counts[attr])
                    for attr in ('insert_count', 'delete_count',
                                 'replace_count', 'total_line_count')
                    if counts.get(attr) is not None
                ]

                s.append(format_html(
                    '<tr {data_attrs}>'
                    ' <td class="diff-file-icon"></td>'
                    ' <td class="diff-file-info">'
                    '  <a href="{url}">{filename}</a>'
                    ' </td>'
                    '</tr>',
                    data_attrs=mark_safe(' '.join(data_attrs)),
                    url=diff_url + '#%d' % i,
                    filename=filediff.source_file))

            num_remaining = file_count - self.MAX_FILES_PREVIEW

            if num_remaining > 0:
                # There are more files remaining than we've shown, so show
                # the count.
                s.append(format_html(
                    '<tr>'
                    ' <td></td>'
                    ' <td class="diff-file-info">{text}</td>'
                    '</tr>',
                    text=_('%s more') % num_remaining))

            s += [
                mark_safe(' </table>'),
                mark_safe('</div>'),
            ]

        return mark_safe(''.join(s))

    def has_value_changed(
        self,
        old_value: Optional[DiffSet],
        new_value: Optional[DiffSet],
    ) -> bool:
        """Return whether the value has changed.

        Args:
            old_value (object):
                The old value of the field.

            new_value (object):
                The new value of the field.

        Returns:
            bool:
            Whether the value of the field has changed.
        """
        # If there's a new diffset at all (in new_value), then it passes
        # the test.
        return new_value is not None

    def load_value(
        self,
        review_request_details: BaseReviewRequestDetails,
    ) -> Optional[DiffSet]:
        """Load a value from the review request or draft.

        Args:
            review_request_details (reviewboard.reviews.models.
                                    base_review_request_details.
                                    BaseReviewRequestDetails):
                The review request or draft.

        Returns:
            object:
            The loaded value.
        """
        # This will be None for a ReviewRequest, and may have a value for
        # ReviewRequestDraft if a new diff was attached.
        return getattr(review_request_details, 'diffset', None)

    def save_value(
        self,
        value: Optional[DiffSet],
    ) -> None:
        """Save the value in the review request or draft.

        Args:
            value (object):
                The new value for the field.
        """
        # The diff is a fake field that doesn't actually exist on the review
        # request, so it deosn't make sense to save.
        pass

    def record_change_entry(
        self,
        changedesc: ChangeDescription,
        old_value: DiffSet,
        new_value: DiffSet,
    ) -> None:
        """Record information on the changed values in a ChangeDescription.

        Args:
            changedesc (reviewboard.changedescs.models.ChangeDescription):
                The change description to record the entry in.

            old_value (object):
                The old value of the field.

            new_value (object):
                The new value of the field.
        """
        diffset = new_value

        review_request = self.review_request_details.get_review_request()

        url = local_site_reverse(
            'view-diff-revision',
            local_site=review_request.local_site,
            args=[review_request.display_id, diffset.revision])

        changedesc.fields_changed['diff'] = {
            'added': [(
                _('Diff r%s') % diffset.revision,
                url,
                diffset.pk,
            )]
        }

    def serialize_change_entry(
        self,
        changedesc,
    ) -> WebAPIResponsePayload:
        """Serialize a change entry for public consumption.

        This will output a version of the change entry for use in the API.
        It can be the same content stored in the
        :py:class:`~reviewboard.changedescs.models.ChangeDescription`, but
        does not need to be.

        Args:
            changedesc (reviewboard.changedescs.models.ChangeDescription):
                The change description whose field is to be serialized.

        Returns:
            dict:
            An appropriate serialization for the field.
        """
        diffset_id = changedesc.fields_changed['diff']['added'][0][2]

        return {
            'added': DiffSet.objects.get(pk=diffset_id),
        }


class FileAttachmentCaptionsField(BaseCaptionsField):
    """Renders caption changes for file attachments.

    This is not shown as an actual displayable field on the review request
    itself. Instead, it is used only during the ChangeDescription rendering
    stage. It is not, however, used for populating entries in
    ChangeDescription.
    """

    field_id = 'file_captions'
    label = _('File Captions')
    obj_map_attr = 'file_attachments_by_id'
    model = FileAttachment
    caption_object_field = 'file_attachment'


class FileAttachmentsField(
    ReviewRequestPageDataMixin[Sequence[FileAttachment]],
    BuiltinFieldMixin[Sequence[FileAttachment]],
    BaseCommaEditableField[FileAttachment],
):
    """Renders removed or added file attachments.

    This is not shown as an actual displayable field on the review request
    itself. Instead, it is used only during the ChangeDescription rendering
    stage. It is not, however, used for populating entries in
    ChangeDescription.
    """

    field_id = 'files'
    label = _('Files')
    model = FileAttachment

    thumbnail_template = 'reviews/changedesc_file_attachment.html'

    def get_change_entry_sections_html(
        self,
        info: Mapping[str, Any],
    ) -> Sequence[ReviewRequestFieldChangeEntrySection]:
        """Return sections of change entries with titles and rendered HTML.

        Args:
            info (dict):
                A dictionary describing how the field has changed. This is
                guaranteed to have ``new`` and ``old`` keys, but may also
                contain ``added`` and ``removed`` keys as well.

        Returns:
            list of dict:
            A list of the change entry sections.
        """
        assert isinstance(info, dict)

        sections: list[ReviewRequestFieldChangeEntrySection] = []

        if 'removed' in info:
            sections.append({
                'title': _('Removed Files'),
                'rendered_html': mark_safe(
                    self.render_change_entry_html(info['removed'])),
            })

        if 'added' in info:
            sections.append({
                'title': _('Added Files'),
                'rendered_html': mark_safe(
                    self.render_change_entry_html(info['added'])),
            })

        return sections

    def render_change_entry_html(
        self,
        info: Sequence[tuple[str, str, int]],
    ) -> SafeString:
        """Render a change entry to HTML.

        This function is expected to return safe, valid HTML. Any values
        coming from a field or any other form of user input must be
        properly escaped.

        Args:
            info (list):
                A list of the changed file attachments. Each item is a 3-tuple
                containing the ``caption``, ``filename``, and the ``pk`` of the
                file attachment in the database.

        Returns:
            django.utils.safestring.SafeString:
            The HTML representation of the change entry.
        """
        # Fetch the template ourselves only once and render it for each item,
        # instead of calling render_to_string() in the loop, so we don't
        # have to locate and parse/fetch from cache for every item.

        template = get_template(self.thumbnail_template)

        data = self.data
        assert data is not None

        items: list[SafeString] = []

        for caption, filename, pk in info:
            try:
                attachment = data.file_attachments_by_id[pk]
            except KeyError:
                try:
                    attachment = FileAttachment.objects.get(pk=pk)
                except FileAttachment.DoesNotExist:
                    continue

            items.append(template.render({
                'model_attrs': self.get_attachment_js_model_attrs(attachment),
                'uuid': uuid.uuid4(),
            }))

        if not items:
            return mark_safe('')

        return format_html(
            '<div class="rb-c-file-attachments">{}</div>',
            mark_safe(''.join(items)))

    def get_attachment_js_model_attrs(
        self,
        attachment: FileAttachment,
        draft: bool = False,
    ) -> dict[str, Any]:
        """Return attributes for the RB.FileAttachment JavaScript model.

        This will determine the right attributes to pass to an instance
        of :js:class:`RB.FileAttachment`, based on the provided file
        attachment.

        Args:
            attachment (reviewboard.attachments.models.FileAttachment):
                The file attachment to return attributes for.

            draft (bool, optional):
                Whether to return attributes for a draft version of the
                file attachment.

        Returns:
            dict:
            The resulting model attributes.
        """
        review_request = self.review_request_details.get_review_request()
        request = self.request

        model_attrs = {
            'canAccessReviewUI': attachment.is_review_ui_accessible_by(
                request.user),
            'downloadURL': attachment.get_absolute_url(),
            'filename': attachment.filename,
            'id': attachment.pk,
            'loaded': True,
            'publishedCaption': attachment.caption,
            'reviewURL': local_site_reverse(
                'file-attachment',
                kwargs={
                    'file_attachment_id': attachment.pk,
                    'review_request_id': review_request.display_id,
                },
                request=request),
            'revision': attachment.attachment_revision,
            'state': self.review_request_details.get_file_attachment_state(
                attachment).value,
            'thumbnailHTML': attachment.thumbnail,
        }

        if draft:
            caption = attachment.draft_caption
        else:
            caption = attachment.caption

        model_attrs['caption'] = caption

        if attachment.attachment_history_id:
            model_attrs['attachmentHistoryID'] = \
                attachment.attachment_history_id

        return model_attrs


class ScreenshotCaptionsField(BaseCaptionsField):
    """Renders caption changes for screenshots.

    This is not shown as an actual displayable field on the review request
    itself. Instead, it is used only during the ChangeDescription rendering
    stage. It is not, however, used for populating entries in
    ChangeDescription.
    """

    field_id = 'screenshot_captions'
    label = _('Screenshot Captions')
    obj_map_attr = 'screenshots_by_id'
    model = Screenshot
    caption_object_field = 'screenshot'


class ScreenshotsField(BaseCommaEditableField[Screenshot]):
    """Renders removed or added screenshots.

    This is not shown as an actual displayable field on the review request
    itself. Instead, it is used only during the ChangeDescription rendering
    stage. It is not, however, used for populating entries in
    ChangeDescription.
    """

    field_id = 'screenshots'
    label = _('Screenshots')
    model = Screenshot


class TargetGroupsField(BuiltinFieldMixin[Sequence[Group]],
                        BaseModelListEditableField[Group]):
    """The Target Groups field on a review request."""

    field_id = 'target_groups'
    label = _('Groups')
    model = Group
    model_name_attr = 'name'

    #: The class name for the JavaScript view representing this field.
    js_view_class = 'RB.ReviewRequestFields.TargetGroupsFieldView'

    def render_item(
        self,
        item: Group,
    ) -> SafeString:
        """Render an item from the list.

        Args:
            item (reviewboard.reviews.models.group.Group):
                The item to render.

        Returns:
            django.utils.safestring.SafeString:
            The rendered item.
        """
        return format_html('<a href="{}">{}</a>',
                           item.get_absolute_url(),
                           item.name)


class TargetPeopleField(BuiltinFieldMixin[Sequence[User]],
                        BaseModelListEditableField[User]):
    """The Target People field on a review request."""

    field_id = 'target_people'
    label = _('People')
    model = User
    model_name_attr = 'username'

    #: The class name for the JavaScript view representing this field.
    js_view_class = 'RB.ReviewRequestFields.TargetPeopleFieldView'

    def render_item(
        self,
        item: User,
    ) -> SafeString:
        """Render an item from the list.

        Args:
            item (django.contrib.auth.models.User):
                The item to render.

        Returns:
            django.utils.safestring.SafeString:
            The rendered item.
        """
        user = item
        extra_classes: list[str] = ['user']

        if not user.is_active:
            extra_classes.append('inactive')

        return format_html(
            '<a href="{0}" class="{1}">{2}</a>',
            local_site_reverse(
                'user',
                local_site=self.review_request_details.local_site,
                args=[user]),
            ' '.join(extra_classes),
            user.username)


class CommitListField(ReviewRequestPageDataMixin[DiffSet],
                      BaseReviewRequestField[DiffSet]):
    """The list of commits for a review request."""

    field_id = 'commit_list'
    label = _('Commits')

    is_editable = False

    js_view_class = 'RB.ReviewRequestFields.CommitListFieldView'

    @cached_property
    def review_request_created_with_history(self) -> bool:
        """Whether the associated review request was created with history."""
        return (
            self.review_request_details
            .get_review_request()
            .created_with_history
        )

    @property
    def should_render(self) -> bool:
        """Whether or not the field should be rendered.

        This field will only be rendered when the review request was created
        with history support. It is also hidden on the diff viewer page,
        because it substantially overlaps with the commit selector.
        """
        from reviewboard.urls import diffviewer_url_names
        url_name = self.request.resolver_match.url_name

        return (self.value is not None and
                self.review_request_created_with_history and
                url_name not in diffviewer_url_names)

    @property
    def can_record_change_entry(self) -> bool:
        """Whether or not the field can record a change entry.

        The field can only record a change entry when the review request has
        been created with history.
        """
        return self.review_request_created_with_history

    def load_value(
        self,
        review_request_details: BaseReviewRequestDetails,
    ) -> DiffSet:
        """Load a value from the review request or draft.

        Args:
            review_request_details (review_request_details.
                                    base_review_request_details.
                                    BaseReviewRequestDetails):
                The review request or draft.

        Returns:
            reviewboard.diffviewer.models.diffset.DiffSet:
            The DiffSet associated with the review request or draft.
        """
        return review_request_details.get_latest_diffset()

    def save_value(
        self,
        value: Optional[DiffSet],
    ) -> None:
        """Save a value to the review request.

        This is intentionally a no-op.

        Args:
            value (reviewboard.diffviewer.models.diffset.DiffSet, unused):
                The current DiffSet
        """
        pass

    def render_value(
        self,
        value: Optional[DiffSet],
    ) -> SafeString:
        """Render the field for the given value.

        Args:
            value (reviewboard.diffviewer.models.diffset.DiffSet):
                The loaded diffset.

        returns:
            django.utils.safestring.SafeString:
            The rendered value.
        """
        if not value:
            return mark_safe('')

        commits = list(value.commits.order_by('pk'))
        context = self._get_common_context(commits)
        context['commits'] = commits

        return render_to_string(
            template_name='reviews/commit_list_field.html',
            request=self.request,
            context=context)

    def has_value_changed(
        self,
        old_value: Optional[DiffSet],
        new_value: Optional[DiffSet],
    ) -> bool:
        """Return whether or not the value has changed.

        Args:
            old_value (reviewboard.diffviewer.models.diffset.DiffSet):
                The :py:class:`~reviewboard.diffviewer.
                models.diffset.DiffSet` from the review_request.

            new_value (reviewboard.diffviewer.models.diffset.DiffSet):
                The :py:class:`~reviewboard.diffviewer.
                models.diffset.DiffSet` from the draft.

        Returns:
            bool:
            Whether or not the value has changed.
        """
        return new_value is not None

    def record_change_entry(
        self,
        changedesc: ChangeDescription,
        old_value: Optional[DiffSet],
        new_value: DiffSet,
    ) -> None:
        """Record the old and new values for this field into the changedesc.

        Args:
            changedesc (reviewboard.changedescs.models.ChangeDescription):
                The change description to record the change into.

            old_value (reviewboard.diffviewer.models.diffset.DiffSet):
                The previous :py:class:`~reviewboard.diffviewer.models.
                diffset.DiffSet` from the review request.

            new_value (reviewboard.diffviewer.models.diffset.DiffSet):
                The new :py:class:`~reviewboard.diffviewer.models.diffset.
                DiffSet` from the draft.
        """
        changedesc.fields_changed[self.field_id] = {
            'old': old_value and old_value.pk,
            'new': new_value.pk,
        }

    def render_change_entry_html(
        self,
        info: Mapping[str, Any],
    ) -> SafeString:
        """Render the change entry HTML for this field.

        Args:
            info (dict):
                The change entry info for this field. See
                :py:meth:`record_change_entry` for the format.

        Returns:
            django.utils.safestring.SafeString:
            The rendered HTML.
        """
        data = self.data
        assert data is not None

        commits = data.commits_by_diffset_id

        if info['old']:
            old_commits = commits[info['old']]
        else:
            old_commits = []

        new_commits = commits[info['new']]

        context = self._get_common_context(chain(old_commits, new_commits))
        context.update({
            'old_commits': old_commits,
            'new_commits': new_commits,
        })

        return render_to_string(
            template_name='reviews/changedesc_commit_list.html',
            request=self.request,
            context=context)

    def serialize_change_entry(
        self,
        changedesc: ChangeDescription,
    ) -> WebAPIResponsePayload:
        """Serialize the changed field entry for the web API.

        Args:
            changdesc (reviewboard.changedescs.models.ChangeDescription):
                The change description being serialized.

        Returns:
            dict:
            A JSON-serializable dictionary representing the change entry for
            this field.
        """
        info = changedesc.fields_changed[self.field_id]

        commits_by_diffset_id = DiffCommit.objects.by_diffset_ids(
            (info['old'], info['new']))

        return {
            key: [
                {
                    'author': commit.author_name,
                    'summary': commit.summary,
                }
                for commit in commits_by_diffset_id[info[key]]
            ]
            for key in ('old', 'new')
        }

    def _get_common_context(
        self,
        commits: Iterable[DiffCommit],
    ) -> dict[str, Any]:
        """Return common context for rending both change entries and the field.

        Args:
            commits (iterable of reviewboard.diffviewer.models.diffcommit.
                     DiffCommit):
                The commits to generate context for.

        Returns:
            dict:
            A dictionary of context.
        """
        review_request_details = self.review_request_details

        submitter_name = review_request_details.submitter.get_full_name()
        include_author_name = not submitter_name
        to_expand: set[int] = set()

        for commit in commits:
            if commit.author_name != submitter_name:
                include_author_name = True

            if commit.summary.strip() != commit.commit_message.strip():
                to_expand.add(commit.pk)

        return {
            'include_author_name': include_author_name,
            'to_expand': list(to_expand),
        }


class MainFieldSet(BaseReviewRequestFieldSet):
    fieldset_id = 'main'
    field_classes = [
        SummaryField,
        DescriptionField,
        TestingDoneField,
    ]


class ExtraFieldSet(BaseReviewRequestFieldSet):
    """A field set that is displayed after the main field set."""

    fieldset_id = 'extra'
    field_classes = [
        CommitListField,
    ]


class InformationFieldSet(BaseReviewRequestFieldSet):
    fieldset_id = 'info'
    label = _('Information')
    field_classes = [
        OwnerField,
        RepositoryField,
        BranchField,
        BugsField,
        DependsOnField,
        BlocksField,
        ChangeField,
        CommitField,
    ]


class ReviewersFieldSet(BaseReviewRequestFieldSet):
    fieldset_id = 'reviewers'
    label = _('Reviewers')
    show_required = True
    field_classes = [
        TargetGroupsField,
        TargetPeopleField,
    ]


class ChangeEntryOnlyFieldSet(BaseReviewRequestFieldSet):
    fieldset_id = '_change_entries_only'
    field_classes = [
        DiffField,
        FileAttachmentCaptionsField,
        ScreenshotCaptionsField,
        FileAttachmentsField,
        ScreenshotsField,
        StatusField,
    ]


builtin_fieldsets = [
    MainFieldSet,
    ExtraFieldSet,
    InformationFieldSet,
    ReviewersFieldSet,
    ChangeEntryOnlyFieldSet,
]
