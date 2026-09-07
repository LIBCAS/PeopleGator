from uuid import uuid4
from datetime import datetime, timezone as tz

class UuidService:
    def __call__(self):
        return self.generate_uuid()

    @staticmethod
    def generate_uuid(*args, **kwargs):
        return uuid4()


class DateTimeService:
    def __call__(self, **kwargs):
        return self.get_datetime_now(**kwargs)

    @staticmethod
    def get_datetime_now(*args, timezone=tz.utc, **kwargs):
        return datetime.now(timezone)
