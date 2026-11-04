from uuid import uuid4
from datetime import datetime, timezone as tz


class UuidService:
    """Callable source of random UUIDs."""

    def __call__(self):
        """Return a new random UUID."""
        return self.generate_uuid()

    @staticmethod
    def generate_uuid(*args, **kwargs):
        """Return a new random UUID; compatibility arguments are ignored.

        Args:
            *args: Compatibility arguments; ignored.
            **kwargs: Compatibility keyword arguments; ignored.
        """
        return uuid4()


class DateTimeService:
    """Callable source of timezone-aware current timestamps."""

    def __call__(self, **kwargs):
        """Return the current datetime, forwarding timezone to get_datetime_now.

        Args:
            **kwargs: Optional timezone; other compatibility keywords are ignored.
        """
        return self.get_datetime_now(**kwargs)

    @staticmethod
    def get_datetime_now(*args, timezone=tz.utc, **kwargs):
        """Return the current datetime in the requested timezone.

        Args:
            timezone: Timezone for the result; defaults to UTC.
            *args: Compatibility arguments; ignored.
            **kwargs: Compatibility keyword arguments; ignored.
        """
        return datetime.now(timezone)
